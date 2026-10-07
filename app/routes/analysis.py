"""BPM and key from the audio (app/analysis.py): start analyses, read results.

Inbox tracks are analysed after every inbox check on their own; library tracks when asked.
Nothing here writes to files: "Use" stages a pending change.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import select

from app import analysis, changes
from app.config import SettingsDep
from app.db import SessionDep
from app.jobs import analysis_job
from app.keys import display
from app.library import TrackFilter
from app.models import InboxTrack, Track
from app.navigation import back_url, reload_page, with_saved_note
from app.templating import templates

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]


class AnalyseRequest(BaseModel):
    track_ids: list[int]
    force: bool = False  # analyse again even if the stored result still holds


def _answer(session, track_id: int, library: bool) -> dict:
    row = analysis.result(session, track_id, library)
    if analysis_job.queued(track_id, library):
        status = "analysing"
    elif row is None:
        status = "not analysed"
    else:
        status = "failed" if row.error else "done"
    answer = {"status": status}
    if row is not None:
        answer |= {
            "bpm": row.bpm,
            "bpm_sure": row.bpm_sure,
            "key": row.key,
            "key_sure": row.key_sure,
            "error": row.error,
            "analysed_at": row.analysed_at,
            **analysis.detail(row),
        }
    return answer


@router.get("/api/analysis", tags=["analysis"])
def analysis_status() -> dict:
    """How far the background analysis is."""
    progress = analysis_job.progress
    return {
        "running": analysis_job.running,
        "workers": analysis_job.workers,  # tracks analysed at the same time
        "total": progress.total,
        "processed": progress.processed,
        "failed": progress.failed,
        "current": progress.current,
    }


@router.post("/api/analysis/stop", tags=["analysis"])
def analysis_stop() -> dict:
    """Forget the tracks still waiting; the one being analysed finishes."""
    return {"dropped": analysis_job.stop()}


@router.post("/api/tracks/analyse", status_code=202, tags=["analysis"])
def analyse_tracks(body: AnalyseRequest, settings: SettingsDep) -> dict:
    """Measure BPM and key of library tracks from the audio (background, low priority)."""
    analysis_job.start(settings, body.track_ids, force=body.force, library=True)
    return {"status": "running", "tracks": len(body.track_ids)}


@router.get("/api/tracks/{track_id}/analysis", tags=["analysis"])
def track_analysis(track_id: int, session: SessionDep) -> dict:
    """What the audio of a library track says: BPM, key, how sure, and why."""
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    return _answer(session, track_id, library=True)


@router.post("/api/inbox/{track_id}/analyse", status_code=202, tags=["analysis"])
def analyse_inbox_track(
    track_id: int, session: SessionDep, settings: SettingsDep, force: bool = True
) -> dict:
    """Measure BPM and key of an inbox track again (background)."""
    if session.get(InboxTrack, track_id) is None:
        raise HTTPException(404)
    analysis_job.start(settings, [track_id], force=force)
    return {"status": "running"}


@router.get("/api/inbox/{track_id}/analysis", tags=["analysis"])
def inbox_analysis(track_id: int, session: SessionDep) -> dict:
    """What the audio of an inbox track says: BPM, key, how sure, and why."""
    if session.get(InboxTrack, track_id) is None:
        raise HTTPException(404)
    return _answer(session, track_id, library=False)


# --- Pages -----------------------------------------------------------------------------


def audio_context(session, track, library: bool = True, genre: str | None = None) -> dict:
    """What the "From the audio" box needs (track page and inbox review page)."""
    row = analysis.result(session, track.id, library)
    found = None
    if row is not None and not row.error:
        found = analysis.decide_for(session, track, library, genre)
    more = analysis.detail(row) if row else {}
    return {
        "audio": {
            "row": row,
            "decision": found,
            "analysing": analysis_job.queued(track.id, library),
            "bpm_alternatives": [
                v for v in more.get("bpm_alternatives", []) if found and v != found.bpm
            ],
            "key_alternatives": [
                v for v in more.get("key_alternatives", []) if found and v != found.key
            ],
            "notes": (more.get("notes", []) + found.notes) if found else [],
            "differences": analysis.differences(track, found) if library and found else [],
        }
    }


@router.post("/tracks/analyse", include_in_schema=False)
async def analyse_many(request: Request, session: SessionDep, settings: SettingsDep, f: FilterDep):
    """The tracks ticked in the list, or all tracks matching its filters (all=true)."""
    form = await request.form()
    if form.get("all") == "true":
        track_ids = list(session.exec(select(Track.id).where(*f.conditions())))
    else:
        track_ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    if track_ids:
        analysis_job.start(settings, track_ids, library=True)
    back = back_url(request, form.get("back"), request.headers.get("referer"), fallback="/tracks")
    return RedirectResponse(back, status_code=303)


@router.post("/analysis/stop", include_in_schema=False)
async def stop_page(request: Request):
    analysis_job.stop()
    back = back_url(request, request.headers.get("referer"), fallback="/tracks")
    return RedirectResponse(back, status_code=303)


@router.get("/partials/analysis", include_in_schema=False)
def progress_partial(request: Request):
    """The "Analysing BPM and key: 12 of 300" line under the track list, polled while it runs."""
    return templates.TemplateResponse(
        request, "partials/analysis_status.html", {"job": analysis_job}
    )


@router.post("/tracks/{track_id}/analyse", include_in_schema=False)
def analyse_one(track_id: int, session: SessionDep, settings: SettingsDep):
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    analysis_job.start(settings, [track_id], force=True, library=True)
    return RedirectResponse(f"/tracks/{track_id}#audio", status_code=303)


@router.get("/tracks/{track_id}/analysis-status", include_in_schema=False)
def analyse_one_status(request: Request, track_id: int):
    """Polled by the "From the audio" box: nothing while analysing, then show the page again."""
    response = Response(status_code=204)
    if not analysis_job.queued(track_id, library=True):
        reload_page(request, response)
    return response


@router.post("/tracks/{track_id}/audio", include_in_schema=False)
async def use_audio(request: Request, track_id: int, session: SessionDep):
    """Stage the audio's BPM or key (form field ``field``) as a pending change."""
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404)
    field = (await request.form()).get("field")
    found = analysis.decide_for(session, track, library=True)
    values = {}
    if field == "bpm" and found.bpm:
        values["bpm"] = f"{found.bpm:g}"
    elif field == "key" and found.key:
        values["key"] = display(found.key, "musical")
    count = changes.stage(session, [track_id], values)[0] if values else 0
    return RedirectResponse(
        with_saved_note(f"/tracks/{track_id}", count) + "#audio", status_code=303
    )


@router.post("/inbox/{track_id:int}/analyse", include_in_schema=False)
async def analyse_inbox_one(
    request: Request, track_id: int, session: SessionDep, settings: SettingsDep
):
    if session.get(InboxTrack, track_id) is None:
        raise HTTPException(404)
    analysis_job.start(settings, [track_id], force=True)
    back = back_url(request, request.headers.get("referer"), fallback=f"/inbox/{track_id}")
    return RedirectResponse(back.split("#")[0] + "#audio", status_code=303)


@router.get("/inbox/{track_id:int}/analysis-status", include_in_schema=False)
def analyse_inbox_status(request: Request, track_id: int):
    response = Response(status_code=204)
    if not analysis_job.queued(track_id):
        reload_page(request, response)
    return response

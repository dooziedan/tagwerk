"""The ReplayGain page: every track's measured loudness next to its ReplayGain tags."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import loudness, preferences
from app.config import SettingsDep
from app.db import SessionDep
from app.forms import read_form
from app.jobs import analysis_job
from app.navigation import with_saved_note
from app.templating import templates

router = APIRouter()

SHOWN = 500  # tracks listed on the page; the rest are fixed with "all" too


class FixRequest(BaseModel):
    track_ids: list[int] | None = None  # None: every track to fix


@router.get("/api/replaygain", tags=["library"])
def replaygain_api(session: SessionDep) -> dict:
    """How the library's ReplayGain compares with the measured loudness (ReplayGain 2.0,
    -18 LUFS), with every track to fix."""
    found = loudness.overview(session)
    return {
        "tracks": found.tracks,
        "measured": found.measured,
        "failed": found.failed,
        "unmeasured": len(found.unmeasured),
        "counts": {status: found.count(status) for status in loudness.STATUSES},
        "to_fix": [
            {
                "track_id": c.track.id,
                "status": c.status,
                "lufs": c.lufs,
                "in_file": c.track.replaygain_track_gain,
                "gain": c.gain,
                "peak": c.peak,
            }
            for c in found.to_fix
        ],
    }


@router.post("/api/replaygain/measure", tags=["library"])
def measure_api(session: SessionDep, settings: SettingsDep) -> dict:
    """Measure every library track without a fresh measurement, in the background."""
    track_ids = loudness.overview(session).unmeasured
    if track_ids:
        analysis_job.start(settings, track_ids, library=True, loudness_only=True)
    return {"queued": len(track_ids)}


@router.post("/api/replaygain/fix", tags=["changes"])
def fix_api(body: FixRequest, session: SessionDep) -> dict:
    """Pending changes with the measured track gain and peak. Review and apply on Changes."""
    return {"pending_changes": loudness.stage_fixes(session, body.track_ids)}


@router.get("/replaygain", response_class=HTMLResponse, include_in_schema=False)
def replaygain_page(request: Request, session: SessionDep):
    found = loudness.overview(session)
    return templates.TemplateResponse(
        request,
        "replaygain.html",
        {
            "found": found,
            "to_fix": found.to_fix,
            "shown": SHOWN,
            "statuses": loudness.STATUSES,
            "reference": loudness.REFERENCE,
            "job": analysis_job,
            "prefs": preferences.load(session),
        },
    )


@router.post("/replaygain/measure", include_in_schema=False)
def measure(session: SessionDep, settings: SettingsDep):
    measure_api(session, settings)
    return RedirectResponse("/replaygain", status_code=303)


@router.post("/replaygain/fix", include_in_schema=False)
async def fix(request: Request, session: SessionDep):
    """The ticked tracks, or every track to fix (all=true)."""
    form = await read_form(request)
    if form.get("all") == "true":
        count = loudness.stage_fixes(session)
    else:
        track_ids = [int(i) for i in form.getlist("track") if str(i).isdigit()]
        count = loudness.stage_fixes(session, track_ids)
    return RedirectResponse(with_saved_note("/changes", count), status_code=303)

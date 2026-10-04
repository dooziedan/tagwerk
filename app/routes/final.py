"""Final tracks: the Final check page, Mark as final, and removing the mark (app/final.py)."""

from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import col, select

from app import final, preferences, writer
from app.config import SettingsDep
from app.db import SessionDep
from app.jobs import busy, write_job
from app.library import CHANGED_OUTSIDE, IS_FINAL, count
from app.models import FinalTrack, Track
from app.templating import templates

router = APIRouter()

# The fields shown on the Final check page, in this order.
CHECK_FIELDS = ["title", "artist", "genre", "bpm", "key", "label", "catalognumber", "comment",
                "album", "albumartist", "date"]  # fmt: skip


# --- API ------------------------------------------------------------------------------------


class UnmarkRequest(BaseModel):
    name: str | None = None  # new filename (the extension stays); None keeps the current one


@router.get("/api/final", tags=["final"])
def final_api(session: SessionDep) -> list[dict]:
    """Final tracks, with when they were marked and whether another program changed them."""
    rows = session.exec(
        select(Track, FinalTrack)
        .join(FinalTrack, col(FinalTrack.track_id) == Track.id)
        .order_by(Track.path)
    )
    return [
        {
            "track_id": t.id,
            "path": t.path,
            "marked_at": f.marked_at,
            "name_before": f.name_before,
            "changed_outside": f.mtime != t.mtime,
        }
        for t, f in rows
    ]


@router.post("/api/final/{track_id}", status_code=202, tags=["final"])
def mark_api(track_id: int, settings: SettingsDep) -> dict:
    """Mark a track as final; renames it if switched on (background job, GET /api/changes/job)."""
    if not write_job.mark_final(settings, track_id):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


@router.delete("/api/final/{track_id}", status_code=202, tags=["final"])
def unmark_api(track_id: int, body: UnmarkRequest, settings: SettingsDep) -> dict:
    """Remove the final mark (background job). Optionally give the file a new name."""
    if not write_job.unmark_final(settings, track_id, body.name):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


# --- Pages ----------------------------------------------------------------------------------


@router.get("/final", response_class=HTMLResponse, include_in_schema=False)
def final_page(
    request: Request, session: SessionDep, id: int | None = None, after: str = "", error: str = ""
):
    """One complete track at a time: check it, then Mark as final or Skip."""
    ready = select(Track).where(final.READY).order_by(Track.path)
    if id is not None:
        track = session.exec(select(Track).where(Track.id == id, final.READY)).first()
    else:
        track = session.exec(ready.where(Track.path > after) if after else ready).first()
        if track is None and after:  # past the end: start again from the top
            track = session.exec(ready).first()
    prefs = preferences.load(session)
    plan = final.plan(session, track) if track else None
    return templates.TemplateResponse(
        request,
        "final.html",
        {
            "prefs": prefs,
            "t": track,
            "plan": plan,
            "fields": [
                (writer.EDITABLE[f], writer.current_value(track, f) if track else None)
                for f in CHECK_FIELDS
            ],
            "ready": count(session, final.READY),
            "finals": count(session, IS_FINAL),
            "changed": count(session, CHANGED_OUTSIDE),
            "job": write_job,
            "busy": busy(),
            "error": error,
        },
    )


@router.post("/final/{track_id}", include_in_schema=False)
def mark_final(track_id: int, session: SessionDep, settings: SettingsDep):
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404)
    if not write_job.mark_final(settings, track_id):
        return RedirectResponse(f"/final?id={track_id}&error=busy", status_code=303)
    return RedirectResponse(f"/final?after={quote(track.path)}", status_code=303)


@router.post("/tracks/{track_id}/unfinal", include_in_schema=False)
async def unmark_final(request: Request, track_id: int, session: SessionDep, settings: SettingsDep):
    """Remove the final mark; the form says what happens to the filename."""
    mark = session.get(FinalTrack, track_id)
    if mark is None:
        return RedirectResponse(f"/tracks/{track_id}", status_code=303)
    form = await request.form()
    choice = form.get("name_choice", "keep")
    name = None
    if choice == "previous" and mark.name_before:
        name = mark.name_before
    elif choice == "typed":
        name = str(form.get("name", "")).strip() or None
    if not write_job.unmark_final(settings, track_id, name):
        return RedirectResponse(f"/tracks/{track_id}?error=busy", status_code=303)
    return RedirectResponse(f"/tracks/{track_id}?unmarking=1", status_code=303)


def final_context(session, track: Track) -> dict:
    """What the track page needs about the final mark."""
    mark = session.get(FinalTrack, track.id)
    complete = session.exec(select(Track.id).where(Track.id == track.id, final.COMPLETE)).first()
    return {
        "final": mark,
        "changed_outside": bool(mark and mark.mtime != track.mtime),
        "can_mark": bool(complete) and mark is None,
        "stem": PurePosixPath(track.path).stem,
    }

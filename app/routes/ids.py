"""Fixing MusicBrainz ID fields that hold other values, e.g. Discogs numbers (app/ids.py).

Fixes become pending changes; nothing is written before Apply.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import select

from app import ids
from app.db import SessionDep
from app.forms import read_form
from app.library import TrackFilter
from app.models import Track
from app.navigation import back_url, with_saved_note

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]


class FixRequest(BaseModel):
    track_ids: list[int]


@router.post("/api/tracks/fix-ids", tags=["library"])
def fix_ids_api(body: FixRequest, session: SessionDep) -> dict:
    """Pending changes that keep real MusicBrainz IDs, move Discogs numbers into the Discogs
    fields and remove anything else. Final tracks are skipped."""
    return {"pending_changes": ids.stage_fixes(session, body.track_ids)}


@router.post("/tracks/fix-ids", include_in_schema=False)
async def fix_ids_many(request: Request, session: SessionDep, f: FilterDep):
    """The tracks ticked in the list, or all tracks matching its filters (all=true)."""
    form = await read_form(request)
    if form.get("all") == "true":
        track_ids = list(session.exec(select(Track.id).where(*f.conditions())))
    else:
        track_ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    saved = ids.stage_fixes(session, track_ids)
    back = back_url(request, form.get("back"), request.headers.get("referer"), fallback="/tracks")
    return RedirectResponse(with_saved_note(back, saved), status_code=303)


@router.post("/tracks/{track_id}/fix-ids", include_in_schema=False)
def fix_ids_one(track_id: int, session: SessionDep):
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    saved = ids.stage_fixes(session, [track_id])
    return RedirectResponse(with_saved_note(f"/tracks/{track_id}", saved), status_code=303)

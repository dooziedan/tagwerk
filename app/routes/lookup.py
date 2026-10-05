"""Looking up library tracks online ("Look up online"; app/identify.py).

Sure values become pending changes on their own; anything else waits on the track page, where
"Use these values" turns one result into pending changes. Nothing is written before Apply.
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import select

from app import changes, genres, identify, writer
from app.config import SettingsDep
from app.db import SessionDep
from app.images import ImageError
from app.jobs import identify_job, image_store
from app.library import TrackFilter
from app.models import Track
from app.navigation import back_url, reload_page, with_saved_note
from app.sources.base import SourceError

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]


class LookupRequest(BaseModel):
    track_ids: list[int]


@router.post("/api/tracks/lookup", status_code=202, tags=["library"])
def lookup_api(body: LookupRequest, settings: SettingsDep) -> dict:
    """Look up library tracks online (background). Sure values become pending changes."""
    identify_job.start(settings, body.track_ids, force=True, library=True)
    return {"status": "running", "tracks": len(body.track_ids)}


@router.get("/api/tracks/{track_id}/online", tags=["library"])
def online_api(track_id: int, session: SessionDep) -> list[dict]:
    """What each online source found for a library track, best match first."""
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    return [
        {"source": f.source, "error": f.error, "candidates": [c.as_dict() for c in f.candidates]}
        for f in identify.results(session, track_id, library=True)
    ]


@router.post("/tracks/lookup", include_in_schema=False)
async def lookup_many(request: Request, session: SessionDep, settings: SettingsDep, f: FilterDep):
    """The tracks ticked in the list, or all tracks matching its filters (all=true)."""
    form = await request.form()
    if form.get("all") == "true":
        ids = list(session.exec(select(Track.id).where(*f.conditions())))
    else:
        ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    if ids:
        identify_job.start(settings, ids, force=True, library=True)
    back = back_url(request, form.get("back"), request.headers.get("referer"), fallback="/tracks")
    sep = "&" if "?" in back else "?"
    return RedirectResponse(f"{back}{sep}looking={len(ids)}", status_code=303)


@router.post("/tracks/{track_id}/lookup", include_in_schema=False)
def lookup_one(track_id: int, session: SessionDep, settings: SettingsDep):
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    identify_job.start(settings, [track_id], force=True, library=True)
    return RedirectResponse(f"/tracks/{track_id}?looking=1#online", status_code=303)


@router.get("/tracks/{track_id}/lookup-status", include_in_schema=False)
def lookup_status(request: Request, track_id: int):
    """Polled by the "Found online" box: nothing while looking up, then show the page again."""
    if identify_job.queued(track_id, library=True):
        return Response(status_code=204)  # still asking: htmx changes nothing
    response = Response(status_code=204)
    reload_page(request, response, drop=("looking",))
    return response


@router.post("/tracks/{track_id}/online", include_in_schema=False)
async def use_online(request: Request, track_id: int, session: SessionDep, settings: SettingsDep):
    """One online result's values (and cover) become pending changes for this track."""
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    form = await request.form()
    found = {r.source: r for r in identify.results(session, track_id, library=True)}
    result = found.get(form.get("source"))
    n = int(form.get("n", 0)) if str(form.get("n", "0")).isdigit() else 0
    if result is None or n >= len(result.candidates):
        return RedirectResponse(f"/tracks/{track_id}", status_code=303)
    candidate = result.candidates[n]
    values = {k: v for k, v in candidate.values.items() if k in writer.EDITABLE and v}
    if "genre" in values:
        values["genre"] = "; ".join(genres.active(session).tidy([values["genre"]]))
    count, errors = changes.stage(session, [track_id], values)
    if errors:  # an odd value (e.g. a date format): stage the others
        rest = {k: v for k, v in values.items() if k not in errors}
        count, _ = changes.stage(session, [track_id], rest)
    if candidate.cover_image or candidate.cover_url:
        try:
            image = candidate.cover_image or image_store(settings).put(
                identify.download_image(candidate.cover_url)
            )
            count += changes.stage_cover(session, [track_id], image)
        except (SourceError, ImageError):
            pass  # the values are staged; the cover stays as it is
    back = f"/tracks/{track_id}?back={quote(str(form.get('back') or '/tracks'), safe='')}"
    return RedirectResponse(with_saved_note(back, count), status_code=303)


def online_context(session, track: Track) -> dict:
    """What the track page needs for its "Found online" box."""
    from app.config import get_settings
    from app.preferences import load

    sources = identify.enabled(get_settings(), load(session))
    return {
        "online": identify.results(session, track.id, library=True),
        "online_sources": [s.label for s in sources],
        "looking_up": identify_job.queued(track.id, library=True),
    }

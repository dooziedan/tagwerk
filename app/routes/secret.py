"""Secret tracks: marking edits and bootlegs so they are never looked up online (app/secret.py).

Library tracks are marked on their page or ticked in the track list; inbox tracks on their
review page or ticked in the inbox (or by putting them into the import folder's Secret folder).
Marking writes nothing into the files.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import secret
from app.config import SettingsDep
from app.db import SessionDep
from app.forms import read_form
from app.jobs import identify_job
from app.models import InboxTrack, SecretTrack, Track
from app.navigation import back_url

router = APIRouter()


class SecretRequest(BaseModel):
    track_ids: list[int]
    secret: bool = True  # False removes the mark


def _note(url: str, on: bool, count: int) -> str:
    """The URL with a one-time note for base.html's toast ("secret_on" / "secret_off")."""
    return url + ("&" if "?" in url else "?") + f"secret_{'on' if on else 'off'}={count}"


def _ids(form) -> list[int]:
    return [int(i) for i in form.getlist("ids") if str(i).isdigit()]


def _set(session, settings, track_ids: list[int], on: bool, inbox: bool) -> int:
    """Mark or unmark. An inbox track that is no longer secret is looked up online at once,
    as any new inbox track would be; library tracks only when the owner asks."""
    if on:
        return secret.mark(session, track_ids, inbox)
    count = secret.unmark(session, track_ids, inbox)
    if inbox and count:
        identify_job.start(settings, track_ids)
    return count


# --- API ------------------------------------------------------------------------------------


@router.post("/api/tracks/secret", tags=["library"])
def secret_api(body: SecretRequest, session: SessionDep, settings: SettingsDep) -> dict:
    """Mark library tracks as secret (edits, bootlegs): never looked up online, complete without
    a cover. What online sources found for them before is forgotten. ``secret: false`` removes
    the mark. Returns how many tracks changed."""
    return {"changed": _set(session, settings, body.track_ids, body.secret, inbox=False)}


@router.post("/api/inbox/secret", tags=["inbox"])
def inbox_secret_api(body: SecretRequest, session: SessionDep, settings: SettingsDep) -> dict:
    """Mark inbox tracks as secret; the mark moves with them into the library. Without the
    mark (``secret: false``), they are looked up online right away."""
    return {"changed": _set(session, settings, body.track_ids, body.secret, inbox=True)}


# --- Pages ----------------------------------------------------------------------------------


@router.post("/tracks/secret", include_in_schema=False)
async def secret_many(request: Request, session: SessionDep, settings: SettingsDep):
    """The tracks ticked in the track list (secret=1 marks them, secret=0 removes the mark)."""
    form = await read_form(request)
    on = form.get("secret") != "0"
    count = _set(session, settings, _ids(form), on, inbox=False)
    back = back_url(request, form.get("back"), request.headers.get("referer"), fallback="/tracks")
    return RedirectResponse(_note(back, on, count), status_code=303)


@router.post("/tracks/{track_id}/secret", include_in_schema=False)
async def secret_one(request: Request, track_id: int, session: SessionDep, settings: SettingsDep):
    if session.get(Track, track_id) is None:
        raise HTTPException(404)
    form = await read_form(request)
    on = form.get("secret") != "0"
    count = _set(session, settings, [track_id], on, inbox=False)
    back = form.get("back")  # the track page's own ← Back, kept
    url = f"/tracks/{track_id}" + (f"?{urlencode({'back': back})}" if back else "")
    return RedirectResponse(_note(url, on, count), status_code=303)


@router.post("/inbox/secret", include_in_schema=False)
async def inbox_secret_many(request: Request, session: SessionDep, settings: SettingsDep):
    """The tracks ticked in the inbox."""
    form = await read_form(request)
    on = form.get("secret") != "0"
    count = _set(session, settings, _ids(form), on, inbox=True)
    show = form.get("show")
    url = f"/inbox?show={show}" if show and show != "all" else "/inbox"
    return RedirectResponse(_note(url, on, count), status_code=303)


@router.post("/inbox/{track_id:int}/secret", include_in_schema=False)
async def inbox_secret_one(
    request: Request, track_id: int, session: SessionDep, settings: SettingsDep
):
    if session.get(InboxTrack, track_id) is None:
        raise HTTPException(404, "Not in the inbox (any more)")
    form = await read_form(request)
    on = form.get("secret") != "0"
    count = _set(session, settings, [track_id], on, inbox=True)
    show = form.get("show")
    url = f"/inbox/{track_id}?show={show}" if show and show != "all" else f"/inbox/{track_id}"
    return RedirectResponse(_note(url, on, count), status_code=303)


def secret_context(session, track: Track) -> dict:
    """What the track page needs about the secret mark."""
    return {"secret": session.get(SecretTrack, track.id)}

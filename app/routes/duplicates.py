"""Duplicates in the library: the groups of copies side by side (app/duplicates.py, ADR 0022).

Tagwerk suggests the copy to keep (the best sound) and lets the owner take over tags and the
cover from the other copies: they become pending changes, reviewed and applied as usual.
Deleting the other copies is done in the file manager (the next scan notices); Tagwerk never
deletes library files. "Keep them all" remembers that a group isn't a problem.
"""

import hashlib

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from app import changes, duplicates, preferences, writer
from app.config import SettingsDep
from app.covers import find_cover
from app.db import SessionDep, get_engine
from app.duplicates import REASONS, load_groups
from app.jobs import image_store
from app.models import NotDuplicate, PendingChange, Track
from app.navigation import with_saved_note
from app.templating import templates

router = APIRouter()

PER_PAGE = 25  # groups per page


class KeepRequest(BaseModel):
    track_ids: list[int]  # every pair of them is kept apart from now on


class TakeRequest(BaseModel):
    keep: int  # the copy to keep
    source: int  # another copy of the same track
    fields: list[str]  # tags as in the edit form ("title", "track", "key" …) and/or "cover"


# --- API ------------------------------------------------------------------------------------


@router.get("/api/duplicates", tags=["library"])
def duplicates_api(session: SessionDep, reason: str = "") -> list[dict]:
    """Groups of tracks that are in the library more than once.

    ``reason``: only groups linked by it: ``file`` (identical file), ``mbid`` (same MusicBrainz
    recording) or ``name`` (same artist and title, about the same length).
    """
    return [
        {
            "group": g.id,
            "name": g.name,
            "reasons": g.reasons,
            "extra_size": g.extra_size,
            "keep": g.suggested.track.id,
            "why": g.why,
            "tracks": [
                {
                    "id": c.track.id,
                    "path": c.track.path,
                    "format": c.track.format,
                    "size": c.track.size,
                    "duration": c.track.duration,
                    "bitrate": c.track.bitrate,
                    "quality": c.quality,
                    "final": c.final,
                    "most_tags": c.most_tags,
                }
                for c in g.copies
            ],
        }
        for g in load_groups(session, reason)
    ]


@router.post("/api/duplicates/keep", tags=["library"])
def keep_api(body: KeepRequest, session: SessionDep, settings: SettingsDep) -> dict:
    """These tracks are not duplicates, or every copy is wanted: never group them again."""
    duplicates.keep_apart(session, body.track_ids)
    groups = duplicates.refresh_library(get_engine(settings.database_url), settings.music_dir)
    return {"groups": groups}


@router.post("/api/duplicates/take", tags=["library"])
def take_api(body: TakeRequest, session: SessionDep, settings: SettingsDep) -> dict:
    """Take tags (and the cover) of one copy over to the copy to keep, as pending changes.

    Review and apply them on the Changes page. Final tracks are locked and get nothing.
    """
    if body.keep == body.source or not duplicates.same_group(session, body.keep, body.source):
        raise HTTPException(400, "Both tracks must be copies of the same track")
    keep, source = session.get(Track, body.keep), session.get(Track, body.source)
    values = {f: writer.current_value(source, f) for f in body.fields if f in writer.EDITABLE}
    staged = changes.stage(session, [keep.id], values, "copy")[0] if values else 0
    if writer.COVER in body.fields:
        found = find_cover(settings.music_dir / source.path)
        if found:
            image = image_store(settings).put(found[0])
            staged += changes.stage_cover(session, [keep.id], image, "copy")
    return {"staged": staged}


@router.post("/api/duplicates/show-again", tags=["library"])
def show_again_api(session: SessionDep, settings: SettingsDep) -> dict:
    """Forget every "keep them all" choice: those groups are shown again."""
    pairs = duplicates.show_again(session)
    groups = duplicates.refresh_library(get_engine(settings.database_url), settings.music_dir)
    return {"forgotten_pairs": pairs, "groups": groups}


# --- Page -----------------------------------------------------------------------------------


@router.get("/duplicates", response_class=HTMLResponse, include_in_schema=False)
def duplicates_page(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    reason: str = "",
    page: int = 1,
    group: int = 0,
    keep: int = 0,
):
    everything = load_groups(session)
    groups = [g for g in everything if not reason or reason in g.reasons]
    if group:  # one group, from a track page or after taking tags over
        groups = [g for g in groups if g.id == group]
        for g in groups:
            g.chosen = keep or None  # "Keep this one instead"
    keepers = [g.keeper.track.id for g in groups]
    pending: dict[int, dict[str, str | None]] = {}
    for change in session.exec(select(PendingChange).where(PendingChange.track_id.in_(keepers))):
        pending.setdefault(change.track_id, {})[change.field] = change.new_value
    pages = max(1, -(-len(groups) // PER_PAGE))
    page = min(max(1, page), pages)
    return templates.TemplateResponse(
        request,
        "duplicates.html",
        {
            "prefs": preferences.load(session),
            "groups": groups[(page - 1) * PER_PAGE : page * PER_PAGE],
            "total_groups": len(everything),
            "total_tracks": sum(len(g.copies) for g in everything),
            "extra_size": sum(g.extra_size for g in everything),
            "counts": {r: sum(1 for g in everything if r in g.reasons) for r in REASONS},
            "reasons": REASONS,
            "reason": reason if reason in REASONS else "",
            "group": group,
            "pending": pending,
            "covers": _cover_ids(settings, groups[(page - 1) * PER_PAGE : page * PER_PAGE]),
            "compared": duplicates.COMPARED,
            "cover_field": writer.COVER,
            "page": page,
            "pages": pages,
            "kept_apart": session.exec(select(func.count()).select_from(NotDuplicate)).one(),
        },
    )


def _cover_ids(settings, groups) -> dict[int, str]:
    """A fingerprint of each shown copy's cover, so only a different cover is offered."""
    found = {}
    for copy in (c for g in groups for c in g.copies if c.track.has_cover):
        cover = find_cover(settings.music_dir / copy.track.path)
        if cover:
            found[copy.track.id] = hashlib.sha1(cover[0]).hexdigest()
    return found


@router.post("/duplicates/keep", include_in_schema=False)
async def keep_form(request: Request, session: SessionDep, settings: SettingsDep):
    form = await request.form()
    ids = [int(i) for i in form.getlist("track_ids") if str(i).isdigit()]
    if len(ids) > 1:
        keep_api(KeepRequest(track_ids=ids), session, settings)
    back = str(form.get("back", ""))
    return RedirectResponse(back if back.startswith("/duplicates") else "/duplicates", 303)


@router.post("/duplicates/take", include_in_schema=False)
async def take_form(request: Request, session: SessionDep, settings: SettingsDep):
    """The "Use" buttons (one tag or the cover) and "Take over missing tags" on the page."""
    form = await request.form()
    keep, source, field = (str(form.get(k, "")) for k in ("keep", "source", "field"))
    if not (keep.isdigit() and source.isdigit()):
        return RedirectResponse("/duplicates", status_code=303)
    group = next((g for g in load_groups(session) if int(keep) in {c.track.id for c in g.copies}),
                 None)  # fmt: skip
    if group is None:
        return RedirectResponse("/duplicates", status_code=303)
    group.chosen = int(keep)
    if field == "missing":  # every tag the keeper lacks, each from a copy that has it
        sources = {
            name: next(c.track.id for c in group.copies if c.value(name) == value)
            for name, value in group.missing.items()
        }
    else:
        sources = {field: int(source)}
    staged = 0
    for name, copy_id in sources.items():
        body = TakeRequest(keep=int(keep), source=copy_id, fields=[name])
        staged += take_api(body, session, settings)["staged"]
    url = f"/duplicates?group={group.id}&keep={keep}"
    return RedirectResponse(with_saved_note(url, staged), status_code=303)


@router.post("/duplicates/show-again", include_in_schema=False)
def show_again_form(session: SessionDep, settings: SettingsDep):
    show_again_api(session, settings)
    return RedirectResponse("/duplicates", status_code=303)

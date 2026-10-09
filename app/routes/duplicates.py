"""Duplicates in the library: the groups of copies side by side (app/duplicates.py, ADR 0022).

Tagwerk suggests the copy to keep (the best sound) and lets the owner take over tags and the
cover from the other copies: they become pending changes, reviewed and applied as usual. The
other copies can be queued for the library trash (ADR 0023): they move there when the owner
applies the pending changes (ADR 0027) and wait until the owner empties the trash. Every
button brings the owner back to the same place on the page. "Keep them all" remembers that a
group isn't a problem.
"""

import hashlib
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app import changes, duplicates, navidrome, preferences, trash, writer
from app.config import SettingsDep
from app.covers import find_cover
from app.db import SessionDep, get_engine
from app.duplicates import REASONS, load_groups
from app.forms import read_form
from app.jobs import busy, image_store, run_now
from app.models import NotDuplicate, PendingChange, Track
from app.templating import templates

router = APIRouter()

PER_PAGE = 25  # groups per page


class KeepRequest(BaseModel):
    track_ids: list[int]  # every pair of them is kept apart from now on


class TrashRequest(BaseModel):
    track_id: int  # the copy to queue for the library trash
    keep: int  # the copy that stays (never trashed)


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


@router.post("/api/duplicates/trash", tags=["changes"])
def trash_api(body: TrashRequest, session: SessionDep) -> dict:
    """Queue a copy for the library trash (``/music/.tagwerk-trash``) as a pending change: it
    moves there when the pending changes are applied, restorable until the trash is emptied.
    Never the copy to keep, never a final track."""
    try:
        duplicates.queue_trash(session, body.track_id, body.keep)
    except trash.TrashError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"queued": body.track_id}


@router.delete("/api/duplicates/trash/{track_id}", tags=["changes"])
def untrash_api(track_id: int, session: SessionDep) -> dict:
    """Forget a queued trash decision: the copy stays in the library."""
    duplicates.unqueue_trash(session, track_id)
    return {"queued": None}


@router.get("/api/library-trash", tags=["library"])
def library_trash_api(settings: SettingsDep) -> list[dict]:
    """Copies in the library trash, newest first."""
    return [d.__dict__ for d in trash.items(settings.music_dir)]


@router.post("/api/library-trash/{entry}/restore", tags=["library"])
def restore_api(entry: str, settings: SettingsDep) -> dict:
    """Put a trashed copy back where it was; it is read into the library again."""
    ok, result = _restore(settings, entry)
    if not ok:
        raise HTTPException(409, result)
    return {"path": result}


@router.delete("/api/library-trash", tags=["library"])
def empty_api(settings: SettingsDep) -> dict:
    """Remove everything in the library trash for good. This can't be undone."""
    ran, removed = run_now(lambda: trash.empty(settings.music_dir))
    if not ran:
        raise HTTPException(409, "A scan or write is running")
    return {"removed": removed}


def _restore(settings, entry: str) -> tuple[bool, str]:
    def work() -> tuple[bool, str]:
        with Session(get_engine(settings.database_url)) as session:
            try:
                track = duplicates.restore_copy(session, settings.music_dir, entry)
            except (trash.TrashError, OSError) as exc:
                return False, str(exc)
            path = track.path
        duplicates.refresh_library(get_engine(settings.database_url), settings.music_dir)
        return True, path

    ran, result = run_now(work)
    if not ran:
        return False, "A scan or write is running; try again when it's finished"
    if result[0]:
        navidrome.rescan_after_write(settings, 1)
    return result


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
    queued = duplicates.queued_trash(session)
    for g in groups:  # the copy kept by queued trash decisions, unless one is picked now
        g.chosen = next((queued[c.track.id] for c in g.copies if c.track.id in queued), None)
    if group:  # one group, from a track page or "Keep this one instead"
        groups = [g for g in groups if g.id == group]
        for g in groups:
            g.chosen = keep or g.chosen
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
            "queued": queued,
            "here": _here(request),
            "covers": _cover_ids(settings, groups[(page - 1) * PER_PAGE : page * PER_PAGE]),
            "compared": duplicates.COMPARED,
            "cover_field": writer.COVER,
            "page": page,
            "pages": pages,
            "kept_apart": session.exec(select(func.count()).select_from(NotDuplicate)).one(),
            "trash": trash.items(settings.music_dir),
            "busy": busy(),
            "note": {
                k: request.query_params.get(k) for k in ("restored", "emptied", "error")
            },  # fmt: skip
        },
    )


_NOTES = {"saved", "restored", "emptied", "error", "done"}  # shown once, not carried back


def _here(request: Request) -> str:
    """This page's address without one-off notes: where the buttons bring the owner back."""
    query = [(k, v) for k, v in parse_qsl(request.url.query) if k not in _NOTES]
    return request.url.path + (f"?{urlencode(query)}" if query else "")


def _back(form, group_id: int | str = "", **notes) -> RedirectResponse:
    """Back to the page the button was on, scrolled to its group, with an optional note."""
    back = urlsplit(str(form.get("back", "")))
    url = back.path if back.path == "/duplicates" else "/duplicates"
    query = [(k, v) for k, v in parse_qsl(back.query) if k not in _NOTES]
    query += [(k, str(v)) for k, v in notes.items()]
    url += f"?{urlencode(query)}" if query else ""
    return RedirectResponse(url + (f"#group-{group_id}" if group_id else ""), status_code=303)


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
    form = await read_form(request)
    ids = [int(i) for i in form.getlist("track_ids") if str(i).isdigit()]
    if len(ids) > 1:
        keep_api(KeepRequest(track_ids=ids), session, settings)
    return _back(form)


@router.post("/duplicates/take", include_in_schema=False)
async def take_form(request: Request, session: SessionDep, settings: SettingsDep):
    """The "Use" buttons (one tag or the cover) and "Take over missing tags" on the page."""
    form = await read_form(request)
    keep, source, field = (str(form.get(k, "")) for k in ("keep", "source", "field"))
    if not (keep.isdigit() and source.isdigit()):
        return _back(form)
    group = next((g for g in load_groups(session) if int(keep) in {c.track.id for c in g.copies}),
                 None)  # fmt: skip
    if group is None:
        return _back(form)
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
    return _back(form, group.id, saved=staged)


@router.post("/duplicates/trash", include_in_schema=False)
async def trash_form(request: Request, session: SessionDep):
    """ "Move to trash": queued as a pending change, moved when the owner applies them."""
    form = await read_form(request)
    track, keep, group = (str(form.get(k, "")) for k in ("track_id", "keep", "group"))
    if not (track.isdigit() and keep.isdigit()):
        return _back(form, group)
    try:
        duplicates.queue_trash(session, int(track), int(keep))
    except trash.TrashError as exc:
        return _back(form, group, error=str(exc))
    return _back(form, group)


@router.post("/duplicates/untrash", include_in_schema=False)
async def untrash_form(request: Request, session: SessionDep):
    """ "Don't trash": the copy stays in the library."""
    form = await read_form(request)
    track = str(form.get("track_id", ""))
    if track.isdigit():
        duplicates.unqueue_trash(session, int(track))
    return _back(form, str(form.get("group", "")))


@router.post("/duplicates/trash/{entry}/restore", include_in_schema=False)
def restore_form(entry: str, settings: SettingsDep):
    ok, result = _restore(settings, entry)
    note = f"restored={quote(result)}" if ok else f"error={quote(result)}"
    return RedirectResponse(f"/duplicates?{note}", status_code=303)


@router.post("/duplicates/trash/empty", include_in_schema=False)
def empty_form(settings: SettingsDep):
    ran, removed = run_now(lambda: trash.empty(settings.music_dir))
    note = f"emptied={removed}" if ran else "error=" + quote("A scan or write is running")
    return RedirectResponse(f"/duplicates?{note}", status_code=303)


@router.post("/duplicates/show-again", include_in_schema=False)
def show_again_form(session: SessionDep, settings: SettingsDep):
    show_again_api(session, settings)
    return RedirectResponse("/duplicates", status_code=303)

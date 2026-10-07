"""Editing tags: edit forms, the review page (pending changes and new genre folders), apply,
history and undo."""

import json
from dataclasses import replace
from typing import Annotated
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, col, select
from starlette.datastructures import FormData, UploadFile

from app import changes, final, folders, preferences, writer
from app.config import Settings, SettingsDep
from app.db import SessionDep
from app.images import MAX_SIZE, ImageError, image_info
from app.jobs import busy, image_store, write_job
from app.library import TrackFilter
from app.models import ChangeSet, Track
from app.navigation import back_url, reload_page, with_saved_note
from app.templating import templates

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]

# Form order per mode: what a DJ edits most comes first.
FIELD_ORDER = {
    "dj": ["bpm", "key", "genre", "comment", "label", "catalognumber",
           "title", "artist", "album", "albumartist", "track", "disc", "date"],
    "collector": ["title", "artist", "album", "albumartist", "track", "disc", "date",
                  "genre", "comment", "label", "catalognumber", "bpm", "key"],
}  # fmt: skip
HINTS = {
    "artist": "Several artists: separate with ;",
    "albumartist": "Several: separate with ;",
    "genre": "Several genres: separate with ;",
    "track": "3 or 3/12",
    "disc": "1 or 1/2",
    "date": "2021 or 2021-05-14",
    "bpm": "e.g. 128 or 127.5",
    "key": "Any notation: Am, 8A, 1m, F# minor",
}


# --- API ------------------------------------------------------------------------------------


class StageRequest(BaseModel):
    track_ids: list[int]
    values: dict[str, str | None]


@router.get("/api/changes", tags=["changes"])
def pending_api(session: SessionDep) -> list[dict]:
    """Pending changes, grouped by track."""
    return [
        {
            "track_id": p.track.id,
            "path": p.track.path,
            "changes": [c.model_dump() for c in p.changes],
        }
        for p in changes.pending(session)
    ]


@router.post("/api/changes", tags=["changes"])
def stage_api(body: StageRequest, session: SessionDep) -> dict:
    """Save edits as pending changes. Nothing is written to files yet."""
    count, errors = changes.stage(session, body.track_ids, body.values)
    if errors:
        raise HTTPException(422, errors)
    return {"pending": count}


@router.delete("/api/changes", tags=["changes"])
def discard_api(session: SessionDep) -> dict:
    changes.discard(session)
    return {"pending": 0}


@router.post("/api/changes/apply", status_code=202, tags=["changes"])
def apply_api(settings: SettingsDep) -> dict:
    """Write all pending changes to the files (background job; see GET /api/changes/job)."""
    if not write_job.apply(settings):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


@router.get("/api/changes/job", tags=["changes"])
def job_api() -> dict:
    p = write_job.progress
    return {"status": write_job.status, "error": write_job.error, **p.__dict__}


@router.get("/api/changesets", tags=["changes"])
def changesets_api(session: SessionDep) -> list[dict]:
    return [c.model_dump() for c in changes.history(session)]


@router.post("/api/changesets/{changeset_id}/undo", status_code=202, tags=["changes"])
def undo_api(changeset_id: int, settings: SettingsDep, session: SessionDep) -> dict:
    if session.get(ChangeSet, changeset_id) is None:
        raise HTTPException(404)
    if not write_job.undo(settings, changeset_id):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


class FolderRequest(BaseModel):
    genre: str


@router.get("/api/folders", tags=["changes"])
def folders_api(session: SessionDep, settings: SettingsDep) -> list[dict]:
    """Proposed genre folders: tracks in _Unsorted whose main genre has no folder yet."""
    return [
        {
            "genre": p.genre,
            "folder": p.folder,
            "exists": p.exists,
            "moves": [
                {"track_id": m.track.id, "from": m.track.path, "to": m.target} for m in p.moves
            ],  # fmt: skip
        }
        for p in folders.proposals(session, settings.music_dir)
    ]


@router.post("/api/folders/create", status_code=202, tags=["changes"])
def create_folder_api(body: FolderRequest, settings: SettingsDep) -> dict:
    """Create the proposed folder for a genre and move its tracks in (background job)."""
    if not write_job.create_folder(settings, body.genre):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


@router.post("/api/folders/keep", tags=["changes"])
def keep_unsorted_api(body: FolderRequest, session: SessionDep) -> dict:
    """Keep a genre's tracks in _Unsorted: no folder is proposed for it any more."""
    folders.keep_unsorted(session, body.genre)
    return {"kept_unsorted": preferences.load(session).kept_unsorted}


# --- Edit forms -----------------------------------------------------------------------------


@router.get("/tracks/{track_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_track_form(request: Request, track_id: int, session: SessionDep):
    track = _track(session, track_id)
    if final.final_ids(session, [track.id]):  # locked: the track page explains how to unlock
        return RedirectResponse(f"/tracks/{track.id}?locked=1", status_code=303)
    prefs = preferences.load(session)
    values = {f: writer.current_value(track, f) or "" for f in writer.EDITABLE}
    pending = {
        c.field: c for p in changes.pending(session) if p.track.id == track_id for c in p.changes
    }
    for name, change in pending.items():
        if name in writer.EDITABLE:
            values[name] = change.new_value or ""
    back = back_url(request, request.query_params.get("back"), fallback="/tracks")
    return _edit_page(request, prefs, [track], values, {}, pending=pending, back=back)


@router.post("/tracks/{track_id}/edit", include_in_schema=False)
async def edit_track(request: Request, track_id: int, session: SessionDep, settings: SettingsDep):
    track = _track(session, track_id)
    form = await request.form()
    values = {f: str(form.get(f, "")) for f in writer.EDITABLE}
    cover, errors = await cover_choice(form, settings)
    if not errors:
        count, errors = changes.stage(session, [track.id], values)
    if errors:
        prefs = preferences.load(session)
        back = back_url(request, form.get("back"), fallback="/tracks")
        return _edit_page(request, prefs, [track], values, errors, back=back, status_code=422)
    if cover is not KEEP_COVER:
        count += changes.stage_cover(session, [track.id], cover)
    back = back_url(request, form.get("back"), fallback="/tracks")
    return RedirectResponse(with_saved_note(back, count), status_code=303)


@router.get("/tracks/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_many_form(request: Request, session: SessionDep, f: FilterDep):
    tracks = _selected(request, session, f)
    if not tracks:
        return RedirectResponse("/tracks", status_code=303)
    prefs = preferences.load(session)
    back = back_url(request, request.headers.get("referer"), fallback="/tracks")
    locked = len(final.final_ids(session, [t.id for t in tracks]))
    return _edit_page(request, prefs, tracks, {}, {}, back=back, locked=locked)


@router.post("/tracks/edit", include_in_schema=False)
async def edit_many(request: Request, session: SessionDep, settings: SettingsDep):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    tracks = list(session.exec(select(Track).where(col(Track.id).in_(ids))).all())
    values = {f: str(form.get(f, "")) for f in writer.EDITABLE if form.get(f"change_{f}") == "on"}
    cover, errors = await cover_choice(form, settings)
    count = 0
    if not errors and not values and cover is KEEP_COVER:
        errors = {"_form": "Tick “Change” next to at least one field, or change the cover art."}
    if not errors:
        count, errors = changes.stage(session, ids, values)
    if errors:
        prefs = preferences.load(session)
        typed = {f: str(form.get(f, "")) for f in writer.EDITABLE}
        back = back_url(request, form.get("back"), fallback="/tracks")
        locked = len(final.final_ids(session, ids))
        return _edit_page(
            request,
            prefs,
            tracks,
            typed,
            errors,
            checked=set(values),
            back=back,
            status_code=422,
            locked=locked,
        )
    if cover is not KEEP_COVER:
        count += changes.stage_cover(session, ids, cover)
    back = back_url(request, form.get("back"), fallback="/tracks")
    return RedirectResponse(with_saved_note(back, count), status_code=303)


KEEP_COVER = object()  # cover art stays as it is


async def cover_choice(form: FormData, settings: Settings) -> tuple[object, dict[str, str]]:
    """The cover art choice in an edit form: KEEP_COVER, None (remove) or an image id."""
    action = form.get("cover_action", "keep")
    if action == "remove":
        return None, {}
    if action != "replace":
        return KEEP_COVER, {}
    upload = form.get("cover_file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return KEEP_COVER, {"cover": "Choose an image file to use as cover art."}
    data = await upload.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        return KEEP_COVER, {"cover": f"The image is too big (more than {MAX_SIZE // 2**20} MB)."}
    try:
        image_info(data)
    except ImageError as exc:
        return KEEP_COVER, {"cover": str(exc)}
    return image_store(settings).put(data), {}


@router.get("/images/{image_id}", include_in_schema=False)
def image(image_id: str, settings: SettingsDep):
    """An uploaded cover, or one saved for undo."""
    store = image_store(settings)
    if not store.exists(image_id):
        raise HTTPException(404)
    path = store.path(image_id)
    with path.open("rb") as f:
        head = f.read(64 * 1024)
    try:
        mime = image_info(head)[0]
    except ImageError:
        raise HTTPException(404) from None
    headers = {"Cache-Control": "public, max-age=31536000, immutable"}  # content never changes
    return FileResponse(path, media_type=mime, headers=headers)


def _edit_page(
    request,
    prefs,
    tracks,
    values,
    errors,
    pending=None,
    checked=None,
    back="/tracks",
    status_code=200,
    locked=0,
):
    many = len(tracks) > 1
    shared = {}
    if many:
        for name in writer.EDITABLE:
            found = {writer.current_value(t, name) for t in tracks}
            shared[name] = next(iter(found)) if len(found) == 1 else None
            if not values.get(name) and len(found) == 1:
                values[name] = next(iter(found)) or ""
    return templates.TemplateResponse(
        request,
        "edit.html",
        {
            "prefs": prefs,
            "tracks": tracks,
            "many": many,
            "fields": [(n, writer.EDITABLE[n]) for n in FIELD_ORDER[prefs.mode]],
            "values": values,
            "shared": shared,
            "errors": errors,
            "hints": HINTS,
            "pending": pending or {},
            "checked": checked or set(),
            "with_cover": sum(1 for t in tracks if t.has_cover),
            "locked": locked,  # final tracks among them: skipped when saving
            "back": back,  # after saving, the user returns here
            # "← Back" without saving: the track page (keeping where it was opened from),
            # or the list for several tracks.
            "cancel": back if many else f"/tracks/{tracks[0].id}?back={quote(back, safe='')}",
        },
        status_code=status_code,
    )


def _selected(request: Request, session: Session, f: TrackFilter) -> list[Track]:
    """Tracks picked in the track list: ids=…, or all=true with the list's filters."""
    query = parse_qs(request.url.query)
    if query.get("all") == ["true"]:
        conditions = f.conditions()
        return list(session.exec(select(Track).where(*conditions).order_by(Track.path)).all())
    ids = [int(i) for i in query.get("ids", []) if i.isdigit()]
    return list(
        session.exec(select(Track).where(col(Track.id).in_(ids)).order_by(Track.path)).all()
    )


# --- Review, apply, history -----------------------------------------------------------------


@router.get("/changes", response_class=HTMLResponse, include_in_schema=False)
def changes_page(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    staged: int | None = None,
    error: str = "",
):
    prefs = preferences.load(session)
    return templates.TemplateResponse(
        request,
        "changes.html",
        {
            "prefs": prefs,
            "items": changes.pending(session),
            "folders": folders.proposals(session, settings.music_dir),
            "labels": writer.LABELS,
            "job": write_job,
            "busy": busy(),
            "staged": staged,
            "error": error,
        },
    )


@router.post("/changes/apply", include_in_schema=False)
async def apply_changes(request: Request, session: SessionDep, settings: SettingsDep):
    form = await request.form()
    prefs = preferences.load(session)
    if not prefs.backup_confirmed:
        if form.get("backup") != "on":
            return RedirectResponse("/changes?error=backup", status_code=303)
        preferences.save(session, replace(prefs, backup_confirmed=True))
    if not changes.pending_count(session):
        return RedirectResponse("/changes", status_code=303)
    if not write_job.apply(settings):
        return RedirectResponse("/changes?error=busy", status_code=303)
    return RedirectResponse("/changes", status_code=303)


@router.post("/changes/folders/create", include_in_schema=False)
async def create_folder(request: Request, settings: SettingsDep):
    genre = str((await request.form()).get("genre", ""))
    if genre and not write_job.create_folder(settings, genre):
        return RedirectResponse("/changes?error=busy", status_code=303)
    return RedirectResponse("/changes", status_code=303)


@router.post("/changes/folders/keep", include_in_schema=False)
async def keep_unsorted(request: Request, session: SessionDep):
    genre = str((await request.form()).get("genre", ""))
    if genre:
        folders.keep_unsorted(session, genre)
    return RedirectResponse("/changes", status_code=303)


@router.post("/changes/folders/propose-again", include_in_schema=False)
def propose_again(session: SessionDep):
    folders.keep_unsorted(session, None)
    return RedirectResponse("/changes", status_code=303)


@router.post("/changes/discard", include_in_schema=False)
def discard_all(session: SessionDep):
    changes.discard(session)
    return RedirectResponse("/changes", status_code=303)


@router.post("/changes/{change_id}/discard", include_in_schema=False)
def discard_one(change_id: int, session: SessionDep):
    changes.discard(session, change_id)
    return RedirectResponse("/changes", status_code=303)


@router.get("/partials/write", response_class=HTMLResponse, include_in_schema=False)
def write_partial(request: Request, was_running: bool = False):
    response = templates.TemplateResponse(request, "partials/write_status.html", {"job": write_job})
    if was_running and not write_job.running:
        reload_page(request, response)  # done: show the result
    return response


@router.get("/changes/history", response_class=HTMLResponse, include_in_schema=False)
def history_page(request: Request, session: SessionDep, error: str = "", page: int = 1):
    pages = changes.history_pages(session)
    page = min(max(1, page), pages)
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "prefs": preferences.load(session),
            "changesets": changes.history(session, page=page),
            "page": page,
            "pages": pages,
            "job": write_job,
            "busy": busy(),
            "error": error,
        },
    )


@router.get("/changes/history/{changeset_id}", response_class=HTMLResponse, include_in_schema=False)
def changeset_page(request: Request, changeset_id: int, session: SessionDep):
    changeset = session.get(ChangeSet, changeset_id)
    if changeset is None:
        raise HTTPException(404)
    rows = [(e, json.loads(e.changes)) for e in changes.entries(session, changeset_id)]
    return templates.TemplateResponse(
        request,
        "changeset.html",
        {
            "prefs": preferences.load(session),
            "c": changeset,
            "rows": rows,
            "labels": writer.LABELS,
            "busy": busy(),
        },
    )


@router.post("/changes/history/{changeset_id}/undo", include_in_schema=False)
def undo_changes(changeset_id: int, settings: SettingsDep, session: SessionDep):
    if session.get(ChangeSet, changeset_id) is None:
        raise HTTPException(404)
    if not write_job.undo(settings, changeset_id):
        return RedirectResponse("/changes/history?error=busy", status_code=303)
    return RedirectResponse("/changes/history", status_code=303)


def _track(session: Session, track_id: int) -> Track:
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    return track

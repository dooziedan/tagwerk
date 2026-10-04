"""Editing tags: edit forms, the review page (pending changes), apply, history and undo."""

import json
from dataclasses import replace
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app import changes, preferences, writer
from app.config import SettingsDep
from app.db import SessionDep
from app.jobs import busy, write_job
from app.library import TrackFilter
from app.models import ChangeSet, Track
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


# --- Edit forms -----------------------------------------------------------------------------


@router.get("/tracks/{track_id}/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_track_form(request: Request, track_id: int, session: SessionDep):
    track = _track(session, track_id)
    prefs = preferences.load(session)
    values = {f: writer.current_value(track, f) or "" for f in writer.EDITABLE}
    pending = {
        c.field: c for p in changes.pending(session) if p.track.id == track_id for c in p.changes
    }
    for name, change in pending.items():
        values[name] = change.new_value or ""
    return _edit_page(request, prefs, [track], values, {}, pending=pending)


@router.post("/tracks/{track_id}/edit", include_in_schema=False)
async def edit_track(request: Request, track_id: int, session: SessionDep):
    track = _track(session, track_id)
    form = await _form(request)
    values = {f: form.get(f, "") for f in writer.EDITABLE}
    count, errors = changes.stage(session, [track.id], values)
    if errors:
        prefs = preferences.load(session)
        return _edit_page(request, prefs, [track], values, errors, status_code=422)
    return RedirectResponse(f"/changes?staged={count}", status_code=303)


@router.get("/tracks/edit", response_class=HTMLResponse, include_in_schema=False)
def edit_many_form(request: Request, session: SessionDep, f: FilterDep):
    tracks = _selected(request, session, f)
    if not tracks:
        return RedirectResponse("/tracks", status_code=303)
    prefs = preferences.load(session)
    return _edit_page(request, prefs, tracks, {}, {})


@router.post("/tracks/edit", include_in_schema=False)
async def edit_many(request: Request, session: SessionDep):
    form = await _form(request, multi=True)
    ids = [int(i) for i in form.get("ids", [])]
    tracks = list(session.exec(select(Track).where(col(Track.id).in_(ids))).all())
    single = {k: v[0] for k, v in form.items()}
    values = {f: single.get(f, "") for f in writer.EDITABLE if single.get(f"change_{f}") == "on"}
    if not values:
        errors = {"_form": "Tick “Change” next to at least one field."}
    else:
        count, errors = changes.stage(session, ids, values)
    if errors:
        prefs = preferences.load(session)
        typed = {f: single.get(f, "") for f in writer.EDITABLE}
        return _edit_page(
            request, prefs, tracks, typed, errors, checked=set(values), status_code=422
        )
    return RedirectResponse(f"/changes?staged={count}", status_code=303)


def _edit_page(request, prefs, tracks, values, errors, pending=None, checked=None, status_code=200):
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
def changes_page(request: Request, session: SessionDep, staged: int | None = None, error: str = ""):
    prefs = preferences.load(session)
    return templates.TemplateResponse(
        request,
        "changes.html",
        {
            "prefs": prefs,
            "items": changes.pending(session),
            "labels": writer.EDITABLE,
            "job": write_job,
            "busy": busy(),
            "staged": staged,
            "error": error,
        },
    )


@router.post("/changes/apply", include_in_schema=False)
async def apply_changes(request: Request, session: SessionDep, settings: SettingsDep):
    form = await _form(request)
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
        response.headers["HX-Refresh"] = "true"  # done: reload to show the result
    return response


@router.get("/changes/history", response_class=HTMLResponse, include_in_schema=False)
def history_page(request: Request, session: SessionDep, error: str = ""):
    return templates.TemplateResponse(
        request,
        "history.html",
        {
            "prefs": preferences.load(session),
            "changesets": changes.history(session),
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
            "labels": writer.EDITABLE,
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


async def _form(request: Request, multi: bool = False) -> dict:
    body = (await request.body()).decode()
    parsed = parse_qs(body, keep_blank_values=True)
    return parsed if multi else {k: v[0] for k, v in parsed.items()}

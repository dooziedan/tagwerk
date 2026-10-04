"""The Inbox page: new music in the import folder, before it joins the library."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from app import genres, preferences, writer
from app.config import SettingsDep, get_settings
from app.covers import find_cover
from app.db import SessionDep
from app.importer import plan
from app.inbox import missing, owner_values, reset_values, review, save_values, set_cover
from app.jobs import inbox_job, scan_job, write_job
from app.models import InboxTrack
from app.proposals import propose, still_missing
from app.routes.changes import FIELD_ORDER, HINTS, KEEP_COVER, cover_choice
from app.routes.scan import scan_state
from app.templating import templates

router = APIRouter()

# Opening the page checks the folder again, but not more often than this.
RECHECK_AFTER = timedelta(seconds=10)


@router.get("/api/inbox", tags=["inbox"])
def inbox_api(session: SessionDep) -> list[dict]:
    """Tracks in the import inbox: what each one is missing and what Tagwerk proposes."""
    result = []
    for t in session.exec(select(InboxTrack).order_by(InboxTrack.path)):
        proposals = propose(t, genres.active(session))
        result.append(
            {
                **t.model_dump(),
                "missing": missing(t),
                "proposals": [p.__dict__ for p in proposals],
                "still_missing": still_missing(t, proposals),
            }
        )
    return result


@router.post("/api/inbox/scan", status_code=202, tags=["inbox"])
def inbox_scan_api(settings: SettingsDep, response: Response) -> dict:
    """Check the import folder for new, changed and removed files (read-only)."""
    if not inbox_job.start(settings):
        response.status_code = 409
    return scan_state(inbox_job)


@router.get("/inbox", response_class=HTMLResponse, include_in_schema=False)
def inbox_page(request: Request, session: SessionDep, settings: SettingsDep):
    configured = settings.import_dir.is_dir()
    if configured and _due():
        inbox_job.start(settings)  # a scan or write may be running: then the list is shown as is
    show = _view(request.query_params.get("show"))
    rows = _rows(session)
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "prefs": preferences.load(session),
            "configured": configured,
            "import_dir": settings.import_dir,
            # All rows are sent; the tabs show and hide them in the browser, so ticks survive.
            "rows": [(r, [k for k, (_, test) in VIEWS.items() if test(r)]) for r in rows],
            "total": len(rows),
            "shown": sum(1 for r in rows if VIEWS[show][1](r)),
            "views": [
                (key, label, sum(1 for r in rows if test(r)))
                for key, (label, test) in VIEWS.items()
            ],
            "show": show,
            "job": inbox_job,
            "write": write_job,
            "busy": _blocked(),
            "error": request.query_params.get("error", ""),
        },
    )


# New tracks are identified first: title and artist lead, then the DJ fields.
INBOX_ORDER = ["title", "artist", "genre", "bpm", "key", "label", "catalognumber", "comment",
               "album", "albumartist", "track", "disc", "date"]  # fmt: skip


@dataclass
class InboxRow:
    track: InboxTrack
    title: str | None  # as it will be after import
    artist: str | None
    changes: int  # fields that will change on import (suggested or set by the owner)
    edited: bool  # the owner set values on the review page
    missing: list[str]

    @property
    def ready(self) -> bool:
        return not self.missing and not self.track.error


# Tabs above the list. A track can be in several (e.g. edited and still needing help).
VIEWS = {
    "all": ("All", lambda r: True),
    "help": ("Needs help", lambda r: bool(r.missing) and not r.track.error),
    "edited": ("Edited", lambda r: r.edited),
    "ready": ("Ready", lambda r: r.ready),
    "unreadable": ("Unreadable", lambda r: bool(r.track.error)),
}


def _view(show) -> str:
    return show if show in VIEWS else "all"


def _ordered(session) -> list[InboxTrack]:
    return list(
        session.exec(select(InboxTrack).order_by(InboxTrack.found_at.desc(), InboxTrack.path))
    )


def _rows(session) -> list["InboxRow"]:
    return [_summary(session, t) for t in _ordered(session)]


def _shown(url: str, show: str) -> str:
    """The URL keeping the chosen tab (?show=...)."""
    return url if show == "all" else f"{url}{'&' if '?' in url else '?'}show={show}"


def _summary(session, track: InboxTrack) -> InboxRow:
    fields = review(session, track, list(writer.EDITABLE))
    proposals = [f.suggestion for f in fields if f.origin == "suggested"]
    missing = still_missing(track, proposals)
    # A value the owner typed fills a gap too.
    mine = {f.field for f in fields if f.origin == "you" and f.value}
    labels = {"Title": "title", "Artist": "artist", "Genre": "genre", "BPM": "bpm", "Key": "key"}
    missing = [m for m in missing if labels.get(m) not in mine]
    changes = sum(1 for f in fields if f.origin != "file" and f.value != f.in_file)
    edited = any(f.origin == "you" for f in fields)
    owner = owner_values(session, track.id)
    if writer.COVER in owner:  # a new cover chosen, or the cover removed
        changes += 1
        edited = True
        has_cover = owner[writer.COVER] is not None
        missing = [m for m in missing if m != "Cover"] + ([] if has_cover else ["Cover"])
    value = {f.field: f.value for f in fields}
    return InboxRow(track, value["title"], value["artist"], changes, edited, missing)


@router.get("/inbox/{track_id:int}", response_class=HTMLResponse, include_in_schema=False)
def inbox_track_page(request: Request, track_id: int, session: SessionDep):
    show = _view(request.query_params.get("show"))
    return _review_page(request, session, _inbox_track(session, track_id), {}, show=show)


@router.post("/inbox/{track_id:int}", include_in_schema=False)
async def inbox_track_save(
    request: Request, track_id: int, session: SessionDep, settings: SettingsDep
):
    track = _inbox_track(session, track_id)
    form = await request.form()
    show = _view(form.get("show"))
    # The next track in the chosen tab, worked out before saving (saving may move this track
    # out of the tab, e.g. from "Needs help" to "Ready").
    _, after = _neighbours(session, track, show)
    if form.get("reset"):
        reset_values(session, track.id)
        return RedirectResponse(_shown(f"/inbox/{track.id}", show), status_code=303)
    typed = {f: str(form.get(f, "")) for f in writer.EDITABLE if f in form}
    cover, errors = await cover_choice(form, settings)
    if not errors:
        errors = save_values(session, track, typed)
    if errors:
        return _review_page(request, session, track, errors, typed, show, status_code=422)
    if cover is not KEEP_COVER:
        set_cover(session, track, cover)
    following = form.get("then")  # "next": continue with the next track; "import": import it
    if following == "import":
        return _start_import([track.id], settings)
    target = after if following == "next" else None
    url = f"/inbox/{target.id}?kept=1" if target else "/inbox?kept=1"  # note: see base.html
    return RedirectResponse(_shown(url, show), status_code=303)


@router.post("/inbox/import", include_in_schema=False)
async def inbox_import(request: Request, settings: SettingsDep):
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    return _start_import(ids, settings)


@router.post("/api/inbox/import", status_code=202, tags=["inbox"])
def inbox_import_api(track_ids: list[int], settings: SettingsDep) -> dict:
    """Import inbox tracks: write their tags, move them into the library (filenames unchanged).

    Runs in the background; progress at GET /api/changes/job.
    """
    inbox_job.wait(30)  # a running inbox check finishes first
    if not write_job.import_tracks(settings, track_ids):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


def _blocked() -> bool:
    """Import can't start: a library scan or a write runs. (The quick inbox check, started by
    opening the page, doesn't count: an import waits for it, see _start_import.)"""
    return scan_job.running or write_job.running


def _start_import(ids: list[int], settings) -> RedirectResponse:
    if not ids:
        return RedirectResponse("/inbox", status_code=303)
    inbox_job.wait(30)  # usually done in under a second
    if not write_job.import_tracks(settings, ids):
        return RedirectResponse("/inbox?error=busy", status_code=303)
    return RedirectResponse("/inbox", status_code=303)


@router.get("/inbox/{track_id:int}/cover", include_in_schema=False)
def inbox_cover(track_id: int, session: SessionDep, settings: SettingsDep):
    track = _inbox_track(session, track_id)
    root = settings.import_dir.resolve()
    path = (root / track.path).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404)
    cover = find_cover(path)
    if cover is None:
        raise HTTPException(404, "No cover art")
    data, mime = cover
    return Response(data, media_type=mime, headers={"Cache-Control": "max-age=3600"})


def _review_page(request, session, track, errors, typed=None, show="all", status_code=200):
    prefs = preferences.load(session)
    order = INBOX_ORDER if prefs.mode == "dj" else FIELD_ORDER["collector"]
    fields = review(session, track, order)
    if typed:  # show what was typed, with the errors
        for f in fields:
            if f.field in typed:
                f.value = typed[f.field]
    tracks = _in_view(session, show)
    if track.id not in [t.id for t in tracks]:  # no longer in the tab: step through all
        show, tracks = "all", _ordered(session)
    before, after = _neighbours(session, track, show)
    return templates.TemplateResponse(
        request,
        "inbox_track.html",
        {
            "prefs": prefs,
            "t": track,
            "fields": fields,
            "errors": errors,
            "hints": HINTS,
            "before": before,
            "after": after,
            "position": next(i for i, t in enumerate(tracks, 1) if t.id == track.id),
            "total": len(tracks),
            "summary": _summary(session, track),
            "plan": plan(session, track, get_settings().music_dir),
            "cover": _cover_field(session, track),
            "busy": _blocked(),
            "show": show,
            "view_label": VIEWS[show][0],
        },
        status_code=status_code,
    )


def _cover_field(session, track: InboxTrack) -> dict:
    """The cover row: the owner's choice if any, else the cover in the file."""
    owner = owner_values(session, track.id)
    chosen = writer.COVER in owner
    if chosen and owner[writer.COVER]:
        src, status = f"/images/{owner[writer.COVER]}", "New cover, written on import"
    elif chosen:
        src, status = None, "Removed on import"
    elif track.has_cover:
        src, status = f"/inbox/{track.id}/cover?v={track.mtime}", "Embedded in the file"
    else:
        src, status = None, "No cover art"
    return {
        "src": src,
        "badge": "your choice" if chosen else None,
        "status": status,
        "removable": bool(src),
        "remove_text": "Removed on import",
        "with_check": False,
        "error": None,
    }


def _in_view(session, show: str) -> list[InboxTrack]:
    return [r.track for r in _rows(session) if VIEWS[show][1](r)]


def _neighbours(
    session, track: InboxTrack, show: str = "all"
) -> tuple[InboxTrack | None, InboxTrack | None]:
    """The tracks before and after this one in the chosen tab."""
    tracks = _in_view(session, show)
    ids = [t.id for t in tracks]
    if track.id not in ids:
        tracks, ids = _ordered(session), [t.id for t in _ordered(session)]
    i = ids.index(track.id)
    return (tracks[i - 1] if i > 0 else None, tracks[i + 1] if i + 1 < len(tracks) else None)


def _inbox_track(session, track_id: int) -> InboxTrack:
    track = session.get(InboxTrack, track_id)
    if track is None:
        raise HTTPException(404, "Not in the inbox (any more)")
    return track


def _due() -> bool:
    if inbox_job.running:
        return False
    finished = inbox_job.finished_at
    return finished is None or datetime.now(UTC) - finished > RECHECK_AFTER


@router.post("/partials/inbox", response_class=HTMLResponse, include_in_schema=False)
def inbox_scan_partial(request: Request, settings: SettingsDep):
    inbox_job.start(settings)
    return _status(request)


@router.get("/partials/inbox", response_class=HTMLResponse, include_in_schema=False)
def inbox_status_partial(request: Request, was_running: bool = False):
    response = _status(request)
    if was_running and not inbox_job.running:
        response.headers["HX-Refresh"] = "true"  # done: reload to show the list
    return response


def _status(request: Request):
    return templates.TemplateResponse(request, "partials/inbox_status.html", {"job": inbox_job})

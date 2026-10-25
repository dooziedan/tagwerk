"""The Releasomat page (ADR 0044): the downloads in Releasomat's folder, which isn't library.

Optional, like everything about Releasomat: without it set up, the menu has no entry and this
page only says so. The files are listed from Tagwerk's own table (``releasomatfile``, read by
``area.sync``), so the page works while Releasomat is down; Releasomat adds which playlists
contain each file and the BPM and key the playlist's source knows. "In your library" and "Better
sound" use the inbox's rules (``LibraryIndex.matches``, ``upgrade.find``), read-only.
"""

import time
import unicodedata
from dataclasses import dataclass
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app import adopt, area, preferences, releasomat, upgrade
from app.config import Settings, SettingsDep
from app.covers import find_cover
from app.db import SessionDep, get_engine
from app.duplicates import LibraryIndex, Match, is_lossless, quality
from app.forms import read_form
from app.jobs import run_now
from app.keys import to_camelot
from app.library import LOW_BITRATE_KBPS
from app.models import ReleasomatFile
from app.templating import templates

router = APIRouter()

PAGE_SIZE = 100  # the area can grow to thousands of files: the page shows them in pages
RECHECK_AFTER = 10  # seconds: opening the page reads the folder again at most this often
_last_check = 0.0
# The last Delete's refusals, shown once on the page it leads back to.
_last_refusals: list[adopt.Outcome] = []


@dataclass
class AreaRow:
    file: ReleasomatFile
    title: str | None  # the file's tags, else what Releasomat downloaded it for
    artist: str | None
    known: releasomat.AreaFile | None  # what Releasomat says about it (None: not answering)
    matches: list[Match]  # likely copies in the library
    better: upgrade.Upgrade | None  # sounds better than its library copy
    low: bool  # lossy below 320 kbps

    @property
    def playlists(self) -> list[releasomat.Playlist]:
        return self.known.playlists if self.known else []

    def has(self, words: str) -> bool:
        """The search box: ``words`` (casefolded) in artist, title or path."""
        text = " ".join(filter(None, (self.artist, self.title, self.file.path)))
        return words in text.casefold()

    @property
    def quality(self) -> str:
        return quality(self.file)

    @property
    def bpm(self) -> float | None:
        return (self.known.wanted.get("bpm") if self.known else None) or None

    @property
    def key(self) -> str | None:
        """The source's key as Camelot ("8A"), or as written when it can't be read."""
        written = self.known.wanted.get("key") if self.known else None
        return to_camelot(written) or written if written else None

    @property
    def downloaded(self) -> str:
        """For sorting, newest first: when Releasomat saved it, else when Tagwerk found it."""
        return (self.known and self.known.downloaded_at) or self.file.found_at.isoformat()


# Tabs above the list. A file can be in several.
VIEWS = {
    "all": ("All", lambda r: True),
    "new": ("Not in library", lambda r: not r.matches),
    "library": ("In your library", lambda r: bool(r.matches) and not r.better),
    "better": ("Better sound", lambda r: r.better is not None),
    "low": ("Low quality", lambda r: r.low),
}


@router.get("/releasomat", response_class=HTMLResponse, include_in_schema=False)
def releasomat_page(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    show: str = "all",
    playlist: int | None = None,
    q: str = "",
    page: int = 1,
):
    prefs = preferences.load(session)
    if area.confirmed(prefs) and _due():
        _check(settings)
    view = _view(settings, session, prefs, show, playlist, q, page)
    note = {k: request.query_params.get(k, "") for k in ("deleted", "refused", "error")}
    refusals = _last_refusals if note["refused"] else []
    return templates.TemplateResponse(
        request, "releasomat.html", {"prefs": prefs, "note": note, "refusals": refusals, **view}
    )


@router.get("/api/releasomat/files", tags=["releasomat"])
def releasomat_files_api(
    session: SessionDep,
    settings: SettingsDep,
    show: str = "all",
    playlist: int | None = None,
    q: str = "",
    page: int = 1,
) -> dict:
    """The files in the Releasomat folder kept out of the library, as the page lists them:
    ``show`` one of all, new, library, better, low; ``playlist`` a Releasomat playlist id;
    ``q`` words in artist, title or path; 100 a page."""
    view = _view(settings, session, preferences.load(session), show, playlist, q, page)
    return {
        "folder": view["folder"],
        "releasomat": view["releasomat"],
        "counts": {key: count for key, _, count in view["views"]},
        "total": view["total"],
        "page": view["page"],
        "pages": view["pages"],
        "files": [_json(row) for row in view["rows"]],
    }


class FileIds(BaseModel):
    ids: list[int]  # ids from GET /api/releasomat/files


@router.post("/api/releasomat/delete", tags=["releasomat"])
def releasomat_delete_api(body: FileIds, settings: SettingsDep) -> dict:
    """Ask Releasomat to delete these files: it deletes them itself (only its own downloads)
    and marks them Don't like, so they're never downloaded again. Tagwerk touches no file.
    One answer per file; 409 when Releasomat isn't answering (nothing is deleted then)."""
    try:
        outcomes = adopt.delete_files(get_engine(settings.database_url), settings, body.ids)
    except adopt.NotReady as exc:
        raise HTTPException(409, str(exc)) from None
    return {"files": [{"path": o.path, "deleted": o.done, "reason": o.reason} for o in outcomes]}


@router.post("/releasomat/delete", include_in_schema=False)
async def releasomat_delete(request: Request, settings: SettingsDep):
    """The page's Delete: one row's button (``one``) or the ticked rows (``ids``)."""
    global _last_refusals
    form = await read_form(request)
    one = form.get("one")
    ids = [int(one)] if one else [int(i) for i in form.getlist("ids")]
    back = str(form.get("back") or "/releasomat")
    back = back if back.startswith("/releasomat") else "/releasomat"
    try:
        outcomes = adopt.delete_files(get_engine(settings.database_url), settings, ids)
    except adopt.NotReady as exc:
        _last_refusals = [adopt.Outcome("", False, str(exc))]
        return RedirectResponse(_with(back, refused=1), status_code=303)
    _last_refusals = [o for o in outcomes if not o.done]
    deleted = sum(o.done for o in outcomes)
    return RedirectResponse(
        _with(back, deleted=deleted, refused=len(_last_refusals)), status_code=303
    )


def _with(url: str, **params) -> str:
    """``url`` with these query parameters added (zeros left out)."""
    extra = urlencode({k: v for k, v in params.items() if v})
    return f"{url}{'&' if '?' in url else '?'}{extra}" if extra else url


@router.post("/api/releasomat/check", tags=["releasomat"])
def releasomat_check_api(settings: SettingsDep) -> dict:
    """Read the Releasomat folder now (new and changed files)."""
    ran, progress = _check(settings)
    if not ran:
        raise HTTPException(409, "A scan or write is running")
    return {"added": progress.added, "updated": progress.updated, "removed": progress.removed}


@router.post("/releasomat/check", include_in_schema=False)
def releasomat_check(settings: SettingsDep):
    _check(settings)
    releasomat.forget_files()
    return RedirectResponse("/releasomat", status_code=303)


@router.get("/releasomat/{file_id:int}/cover", include_in_schema=False)
def releasomat_cover(file_id: int, session: SessionDep, settings: SettingsDep):
    root = area.area_dir(settings, preferences.load(session))
    row = session.get(ReleasomatFile, file_id)
    if root is None or row is None:
        raise HTTPException(404)
    base = root.resolve()
    path = (base / row.path).resolve()
    cover = find_cover(path) if path.is_relative_to(base) else None
    if cover is None:
        raise HTTPException(404, "No cover art")
    data, mime = cover
    return Response(data, media_type=mime, headers={"Cache-Control": "max-age=3600"})


def _due() -> bool:
    return time.monotonic() - _last_check > RECHECK_AFTER


def _check(settings: Settings):
    """Read the area now, unless a job runs (then the list is shown as it is)."""
    global _last_check
    _last_check = time.monotonic()
    return run_now(lambda: area.sync(get_engine(settings.database_url), settings))


def _view(settings, session, prefs, show, playlist, q, page) -> dict:
    """Everything the page and its API show."""
    folder = area.confirmed(prefs)
    known, problem = _from_releasomat(settings)
    rows = _rows(session, settings, prefs, known) if folder else []
    playlists = sorted(
        {p.id: p for f in known.values() for p in f.playlists}.values(),
        key=lambda p: p.name.lower(),
    )
    show = show if show in VIEWS else "all"
    words = q.strip().casefold()
    shown = [
        r for r in rows
        if VIEWS[show][1](r)
        and (playlist is None or any(p.id == playlist for p in r.playlists))
        and (not words or r.has(words))
    ]  # fmt: skip
    pages = max(1, ceil(len(shown) / PAGE_SIZE))
    page = min(max(page, 1), pages)
    kept = {"show": show if show != "all" else "", "playlist": playlist or "", "q": q.strip()}

    def page_link(number: int) -> str:  # another page, with the same tab and filters
        return "/releasomat?" + urlencode({k: v for k, v in kept.items() if v} | {"page": number})

    return {
        "page_link": page_link,
        # Delete (and Adopt) only when Releasomat answers: it does the deleting.
        "can_delete": bool(folder) and releasomat.configured(settings) and problem is None,
        "here": page_link(page),  # where Delete leads back to
        "configured": area.configured(settings, prefs),
        "folder": folder,
        "proposed": area.proposed(settings, session),
        "music_dir": settings.music_dir.as_posix(),
        "connected": releasomat.configured(settings),
        "releasomat": {"answers": problem is None, "problem": problem},
        "views": [(key, label, sum(map(test, rows))) for key, (label, test) in VIEWS.items()],
        "show": show,
        "playlists": playlists,
        "playlist": playlist,
        "q": q.strip(),
        "rows": shown[(page - 1) * PAGE_SIZE : page * PAGE_SIZE],
        "total": len(shown),
        "page": page,
        "pages": pages,
        "low_kbps": LOW_BITRATE_KBPS,
    }  # fmt: skip


def _from_releasomat(settings: Settings) -> tuple[dict[str, releasomat.AreaFile], str | None]:
    """Releasomat's files by their path (Unicode NFC), and why it didn't answer (or None)."""
    if not releasomat.configured(settings):
        return {}, None
    try:
        _folder, found = releasomat.files_cached(settings)
    except releasomat.ReleasomatError as exc:
        return {}, exc.message
    return {unicodedata.normalize("NFC", f.path): f for f in found}, None


def _rows(session: Session, settings: Settings, prefs, known: dict) -> list[AreaRow]:
    """Every area file's row, newest download first. The library is read once (LibraryIndex)."""
    root = area.area_dir(settings, prefs)
    library = LibraryIndex.load(session)
    rows = []
    for file in session.exec(select(ReleasomatFile)):
        about = known.get(unicodedata.normalize("NFC", file.path))
        wanted = about.wanted if about else {}
        title = file.title or wanted.get("title")
        artist = file.artist or wanted.get("artist")
        matches = [] if file.error else library.matches(
            file, title, artist, root, settings.music_dir
        )  # fmt: skip
        low = (
            not file.error
            and not is_lossless(file)
            and bool(file.bitrate)
            and file.bitrate < LOW_BITRATE_KBPS * 1000 * 0.98
        )
        rows.append(AreaRow(file, title, artist, about, matches, upgrade.find(file, matches), low))
    return sorted(rows, key=lambda r: (r.downloaded, r.file.path), reverse=True)


def _json(row: AreaRow) -> dict:
    f = row.file
    return {
        "id": f.id,
        "path": f.path,
        "releasomat_id": row.known.id if row.known else None,
        "title": row.title,
        "artist": row.artist,
        "format": f.format,
        "quality": row.quality,
        "low_quality": row.low,
        "duration": f.duration,
        "size": f.size,
        "error": f.error,
        "bpm": row.bpm,
        "key": row.key,
        "playlists": [{"id": p.id, "name": p.name, "url": p.url} for p in row.playlists],
        "in_library": [{"track_id": m.track.id, "path": m.track.path, "why": m.reason}
                       for m in row.matches],
        "better_sound": {"than": row.better.library.path, "why": row.better.reason}
        if row.better else None,
    }  # fmt: skip

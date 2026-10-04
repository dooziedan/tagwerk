"""Browsing the library: track list, track page, artists, albums. Read-only."""

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlmodel import select

from app import preferences
from app.config import SettingsDep
from app.covers import find_cover
from app.db import SessionDep
from app.library import FLAGS, MISSING, SORTS, TrackFilter, find_tracks, list_albums, list_artists
from app.models import PendingChange, RawTag, Track
from app.rawtags import SYSTEMS, used_as
from app.tags import FORMATS
from app.templating import templates

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]


@router.get("/api/tracks", tags=["library"])
def tracks_api(
    session: SessionDep, f: FilterDep, sort: str = "artist", desc: bool = False, page: int = 1
) -> dict:
    """Tracks matching the filters, 50 per page."""
    result = find_tracks(session, f, sort, desc, page)
    return {
        "total": result.total,
        "page": result.page,
        "pages": result.pages,
        "tracks": [t.model_dump() for t in result.tracks],
    }


@router.get("/api/tracks/{track_id}", tags=["library"])
def track_api(track_id: int, session: SessionDep) -> dict:
    track = _get_track(session, track_id)
    raw = session.exec(select(RawTag).where(RawTag.track_id == track_id)).all()
    return {**track.model_dump(), "raw": [r.model_dump(exclude={"id", "track_id"}) for r in raw]}


@router.get("/api/artists", tags=["library"])
def artists_api(session: SessionDep, q: str = "") -> list[dict]:
    return [asdict(a) for a in list_artists(session, q)]


@router.get("/api/albums", tags=["library"])
def albums_api(session: SessionDep, q: str = "", artist: str = "") -> list[dict]:
    return [asdict(a) for a in list_albums(session, q, artist)]


@router.get("/tracks", response_class=HTMLResponse, include_in_schema=False)
def tracks_page(
    request: Request,
    session: SessionDep,
    f: FilterDep,
    sort: str = "artist",
    desc: bool = False,
    page: int = 1,
):
    prefs = preferences.load(session)
    result = find_tracks(session, f, sort, desc, page)
    return templates.TemplateResponse(
        request,
        "tracks.html",
        {
            "prefs": prefs,
            "f": f,
            "result": result,
            "sort": sort if sort in SORTS else "artist",
            "desc": desc,
            "sorts": SORTS,
            "chips": f.chips(prefs.key_notation),
            "formats": sorted(set(FORMATS.values())),
            "missing_options": list(MISSING),
            "flags": {k: label for k, (label, _) in FLAGS.items()},
        },
    )


@router.get("/tracks/{track_id}", response_class=HTMLResponse, include_in_schema=False)
def track_page(request: Request, track_id: int, session: SessionDep):
    track = _get_track(session, track_id)
    raw = session.exec(
        select(RawTag).where(RawTag.track_id == track_id).order_by(RawTag.system, RawTag.name)
    ).all()
    return templates.TemplateResponse(
        request,
        "track.html",
        {
            "prefs": preferences.load(session),
            "t": track,
            "raw": [(r, used_as(r.system, r.name)) for r in raw],
            "systems": SYSTEMS,
            "folder": track.path.rsplit("/", 1)[0] if "/" in track.path else "",
            "pending": session.exec(
                select(PendingChange).where(PendingChange.track_id == track_id)
            ).all(),
        },
    )


@router.get("/tracks/{track_id}/cover", include_in_schema=False)
def track_cover(track_id: int, session: SessionDep, settings: SettingsDep):
    track = _get_track(session, track_id)
    music = settings.music_dir.resolve()
    path = (music / track.path).resolve()
    if not path.is_relative_to(music):  # never serve anything outside the music folder
        raise HTTPException(404)
    cover = find_cover(path)
    if cover is None:
        raise HTTPException(404, "No cover art")
    data, mime = cover
    return Response(data, media_type=mime, headers={"Cache-Control": "max-age=3600"})


@router.get("/artists", response_class=HTMLResponse, include_in_schema=False)
def artists_page(request: Request, session: SessionDep, q: str = ""):
    return templates.TemplateResponse(
        request,
        "artists.html",
        {"prefs": preferences.load(session), "artists": list_artists(session, q), "q": q},
    )


@router.get("/albums", response_class=HTMLResponse, include_in_schema=False)
def albums_page(request: Request, session: SessionDep, q: str = "", artist: str = ""):
    return templates.TemplateResponse(
        request,
        "albums.html",
        {
            "prefs": preferences.load(session),
            "albums": list_albums(session, q, artist),
            "q": q,
            "artist": artist,
        },
    )


def _get_track(session, track_id: int) -> Track:
    track = session.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    return track

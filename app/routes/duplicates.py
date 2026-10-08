"""Duplicates in the library: the groups of copies side by side (app/duplicates.py, ADR 0022).

Tagwerk only points copies out. Deleting one is done in the file manager (the next scan notices);
"Keep them all" remembers that a group isn't a problem, so it isn't shown again.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from app import duplicates, preferences
from app.config import SettingsDep
from app.db import SessionDep, get_engine
from app.duplicates import REASONS, load_groups
from app.models import NotDuplicate
from app.templating import templates

router = APIRouter()

PER_PAGE = 25  # groups per page


class KeepRequest(BaseModel):
    track_ids: list[int]  # every pair of them is kept apart from now on


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
            "tracks": [
                {
                    "id": c.track.id,
                    "path": c.track.path,
                    "format": c.track.format,
                    "size": c.track.size,
                    "duration": c.track.duration,
                    "bitrate": c.track.bitrate,
                    "final": c.final,
                    "best_sound": c.best_sound,
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


@router.post("/api/duplicates/show-again", tags=["library"])
def show_again_api(session: SessionDep, settings: SettingsDep) -> dict:
    """Forget every "keep them all" choice: those groups are shown again."""
    pairs = duplicates.show_again(session)
    groups = duplicates.refresh_library(get_engine(settings.database_url), settings.music_dir)
    return {"forgotten_pairs": pairs, "groups": groups}


# --- Page -----------------------------------------------------------------------------------


@router.get("/duplicates", response_class=HTMLResponse, include_in_schema=False)
def duplicates_page(
    request: Request, session: SessionDep, reason: str = "", page: int = 1, group: int = 0
):
    everything = load_groups(session)
    groups = [g for g in everything if not reason or reason in g.reasons]
    if group:  # one group, from a track page
        groups = [g for g in groups if g.id == group]
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
            "page": page,
            "pages": pages,
            "kept_apart": session.exec(select(func.count()).select_from(NotDuplicate)).one(),
            "fields": [
                ("Title", "title"),
                ("Artist", "artist"),
                ("Album", "album"),
                ("Genre", "genre"),
                ("BPM", "bpm"),
                ("Key", "key_camelot"),
                ("Year", "year"),
                ("Label", "label"),
                ("Catalog no.", "catalognumber"),
            ],
        },
    )


@router.post("/duplicates/keep", include_in_schema=False)
async def keep_form(request: Request, session: SessionDep, settings: SettingsDep):
    form = await request.form()
    ids = [int(i) for i in form.getlist("track_ids") if str(i).isdigit()]
    if len(ids) > 1:
        keep_api(KeepRequest(track_ids=ids), session, settings)
    back = str(form.get("back", ""))
    return RedirectResponse(back if back.startswith("/duplicates") else "/duplicates", 303)


@router.post("/duplicates/show-again", include_in_schema=False)
def show_again_form(session: SessionDep, settings: SettingsDep):
    show_again_api(session, settings)
    return RedirectResponse("/duplicates", status_code=303)

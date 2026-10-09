"""The Genre spellings page: one genre written in several ways, merged into one spelling."""

from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import genre_merge, preferences
from app.db import SessionDep
from app.forms import read_form
from app.navigation import with_saved_note
from app.templating import templates

router = APIRouter()


class MergeRequest(BaseModel):
    agreed: dict[str, str]  # group key (from /api/genres/spellings) -> the spelling to keep


@router.get("/api/genres/spellings", tags=["library"])
def spellings_api(session: SessionDep) -> list[dict]:
    """Genres written in more than one way ("Drum and Bass", "DnB"), with tracks per spelling."""
    return [asdict(g) | {"choices": g.choices} for g in genre_merge.groups(session)]


@router.post("/api/genres/merge", tags=["changes"])
def merge_api(body: MergeRequest, session: SessionDep) -> dict:
    """Pending changes that write one spelling per genre. Review and apply them on Changes."""
    return {"pending_changes": genre_merge.stage_merge(session, body.agreed)}


@router.get("/genres", response_class=HTMLResponse, include_in_schema=False)
def genres_page(request: Request, session: SessionDep):
    return templates.TemplateResponse(
        request,
        "genres.html",
        {"groups": genre_merge.groups(session), "prefs": preferences.load(session)},
    )


@router.post("/genres/merge", include_in_schema=False)
async def merge(request: Request, session: SessionDep):
    """The ticked genres, each with the spelling picked for it."""
    form = await read_form(request)
    agreed = {key: str(form.get(f"agreed:{key}", "")) for key in form.getlist("merge")}
    count = genre_merge.stage_merge(session, agreed)
    return RedirectResponse(with_saved_note("/changes", count), status_code=303)

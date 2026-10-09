"""The Mix names page: "(club remix)" in titles written as "(Club Remix)"."""

from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import mix_names
from app.db import SessionDep
from app.forms import read_form
from app.navigation import with_saved_note
from app.templating import templates

router = APIRouter()


class FixRequest(BaseModel):
    track_ids: list[int] | None = None  # None: every track in /api/mix-names


@router.get("/api/mix-names", tags=["library"])
def mix_names_api(session: SessionDep) -> list[dict]:
    """Titles with mix names in lower case ("Rio (club remix)"), each with the fixed title."""
    return [asdict(f) for f in mix_names.fixes(session)]


@router.post("/api/mix-names/fix", tags=["changes"])
def fix_api(body: FixRequest, session: SessionDep) -> dict:
    """Pending changes with the capitalised titles. Review and apply them on Changes."""
    return {"pending_changes": mix_names.stage_fixes(session, body.track_ids)}


@router.get("/mix-names", response_class=HTMLResponse, include_in_schema=False)
def mix_names_page(request: Request, session: SessionDep):
    return templates.TemplateResponse(
        request, "mix_names.html", {"fixes": mix_names.fixes(session)}
    )


@router.post("/mix-names/fix", include_in_schema=False)
async def fix(request: Request, session: SessionDep):
    """The ticked tracks."""
    form = await read_form(request)
    track_ids = [int(i) for i in form.getlist("track") if str(i).isdigit()]
    count = mix_names.stage_fixes(session, track_ids)
    return RedirectResponse(with_saved_note("/changes", count), status_code=303)

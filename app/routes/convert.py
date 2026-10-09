"""Converting tracks to AIFF: the review page and the API (app/convert.py)."""

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import col, select

from app import convert, preferences
from app.config import SettingsDep
from app.db import SessionDep
from app.forms import read_form
from app.jobs import busy, write_job
from app.library import TrackFilter
from app.models import Track
from app.routes.changes import _selected
from app.templating import templates

router = APIRouter()
FilterDep = Annotated[TrackFilter, Depends()]


class ConvertRequest(BaseModel):
    track_ids: list[int]


@router.post("/api/convert/plan", tags=["convert"])
def plan_api(body: ConvertRequest, session: SessionDep, settings: SettingsDep) -> dict:
    """What converting these tracks to AIFF would do, and why some would be skipped."""
    tracks = list(session.exec(select(Track).where(col(Track.id).in_(body.track_ids))))
    return {
        "unavailable": convert.available(settings),
        "tracks": [
            {
                "track_id": p.track.id,
                "path": p.track.path,
                "target": None if p.skip else p.target,
                "skip": p.skip,
            }
            for p in convert.plan(session, settings, tracks)
        ],
    }


@router.post("/api/convert", status_code=202, tags=["convert"])
def convert_api(body: ConvertRequest, settings: SettingsDep) -> dict:
    """Convert tracks to AIFF (background job, progress at GET /api/changes/job)."""
    reason = convert.available(settings)
    if reason:
        raise HTTPException(422, reason)
    if not write_job.convert(settings, body.track_ids):
        raise HTTPException(409, "Another scan or write is running")
    return {"status": "running"}


@router.get("/convert", response_class=HTMLResponse, include_in_schema=False)
def convert_page(request: Request, session: SessionDep, settings: SettingsDep, f: FilterDep):
    """Review: which of the picked tracks become AIFF, where they go, and which are skipped."""
    tracks = _selected(request, session, f)
    plans = convert.plan(session, settings, tracks)
    return templates.TemplateResponse(
        request,
        "convert.html",
        {
            "prefs": preferences.load(session),
            "plans": plans,
            "ready": [p for p in plans if not p.skip],
            "unavailable": convert.available(settings),
            "originals_dir": settings.originals_dir,
            "job": write_job,
            "busy": busy(),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/convert", include_in_schema=False)
async def convert_start(request: Request, settings: SettingsDep):
    form = await read_form(request)
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    back = "/convert?" + urlencode([("ids", i) for i in ids])
    if not ids or convert.available(settings):
        return RedirectResponse(back, status_code=303)
    if not write_job.convert(settings, ids):
        return RedirectResponse(back + "&error=busy", status_code=303)
    return RedirectResponse(back, status_code=303)

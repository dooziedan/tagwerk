"""The dashboard: library statistics and the scan control."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.config import SettingsDep
from app.db import SessionDep
from app.jobs import scan_job
from app.routes.system import setup_status
from app.stats import library_stats
from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard(request: Request, settings: SettingsDep, session: SessionDep):
    status = setup_status(request, settings)
    stats = library_stats(session) if status["database_ok"] else None
    return templates.TemplateResponse(
        request, "dashboard.html", {"status": status, "stats": stats, "job": scan_job}
    )


@router.get("/api/stats", tags=["library"])
def stats(request: Request, session: SessionDep) -> dict:
    """The numbers shown on the dashboard."""
    if getattr(request.app.state, "db_error", None):
        raise HTTPException(503, "Database not available, see /api/status")
    return asdict(library_stats(session))

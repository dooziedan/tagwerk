"""Home (what needs you, recently added, the scan control) and Statistics (the charts)."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import changes, preferences
from app.config import SettingsDep
from app.db import SessionDep
from app.folders import proposal_count
from app.home import home_data
from app.jobs import analysis_job, identify_job, scan_job, write_job
from app.preferences import PreferencesDep
from app.routes.system import setup_status
from app.stats import HEAT_AXES, heatmap, library_stats
from app.templating import templates
from app.work import home_line, work_stats

router = APIRouter()


def _inbox(session) -> dict:
    """How many inbox tracks are ready to import and how many need the owner's help."""
    from app.routes.inbox import counts  # routes.inbox imports a lot; only needed here

    return counts(session)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def home_page(request: Request, settings: SettingsDep, session: SessionDep):
    status = setup_status(request, settings)
    prefs = data = work = None
    waiting = {"inbox": None, "pending": 0, "folders": 0}
    if status["database_ok"]:
        prefs = preferences.load(session)
        if not prefs.setup_done and status["ok"]:
            return RedirectResponse("/setup", status_code=303)  # first start: the wizard
        data = home_data(session)
        waiting = _waiting(session, settings)
        work = home_line(session)
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "status": status,
            "prefs": prefs,
            "home": data,
            **waiting,
            "work": work,  # (tag values written, tracks) for "Tagwerk's work"
            "job": scan_job,
            "analysis_job": analysis_job,
            "identify_job": identify_job,
            "write_job": write_job,
        },
    )


@router.get("/partials/home/waiting", response_class=HTMLResponse, include_in_schema=False)
def waiting_partial(request: Request, settings: SettingsDep, session: SessionDep):
    """Home's "Waiting for you" card, reloaded every minute while Home stays open."""
    return templates.TemplateResponse(
        request,
        "partials/home_waiting.html",
        {
            **_waiting(session, settings),
            "analysis_job": analysis_job,
            "identify_job": identify_job,
            "write_job": write_job,
        },
    )


def _waiting(session, settings) -> dict:
    """The numbers in "Waiting for you" (the unread notifications come from the template)."""
    return {
        "inbox": _inbox(session) if settings.import_dir.is_dir() else None,
        "pending": changes.pending_count(session),
        "folders": proposal_count(session, settings.music_dir),  # new genre folders proposed
    }


@router.get("/stats", response_class=HTMLResponse, include_in_schema=False)
def stats_page(request: Request, session: SessionDep, rows: str = "key", cols: str = "tempo"):
    prefs = preferences.load(session)
    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "prefs": prefs,
            "stats": library_stats(session, prefs),
            "heat": heatmap(session, rows, cols, prefs.key_notation),
            "work": work_stats(session),
            "axes": HEAT_AXES,
            "job": scan_job,
        },
    )


@router.get("/api/home", tags=["library"])
def home_api(session: SessionDep) -> dict:
    """What the Home page shows: problems with their track lists, recently added tracks."""
    data = home_data(session)
    return {
        **{k: v for k, v in asdict(data).items() if k != "recent"},
        "set_ready_percent": data.set_ready_percent,
        "recent": [t.model_dump() for t in data.recent],
        "pending_changes": changes.pending_count(session),
    }


@router.get("/api/stats", tags=["library"])
def stats(request: Request, session: SessionDep, prefs: PreferencesDep) -> dict:
    """The numbers shown on the Statistics page."""
    if getattr(request.app.state, "db_error", None):
        raise HTTPException(503, "Database not available, see /api/status")
    return asdict(library_stats(session, prefs))


@router.get("/api/stats/work", tags=["library"])
def work_api(session: SessionDep) -> dict:
    """What Tagwerk has done for the library, from the History: tag values filled in,
    corrected and removed per field, where they came from, imports, set-ready before/after."""
    return asdict(work_stats(session))


@router.get("/api/stats/heatmap", tags=["library"])
def heatmap_api(
    session: SessionDep, prefs: PreferencesDep, rows: str = "key", cols: str = "tempo"
) -> dict:
    """Tracks per combination of two values, e.g. key x tempo. Axes: key, tempo, year (release
    year), added (year added), genre, format."""
    return asdict(heatmap(session, rows, cols, prefs.key_notation))

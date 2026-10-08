"""Start a library scan and follow its progress."""

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from app.config import SettingsDep
from app.jobs import ScanJob, scan_job
from app.navigation import reload_page
from app.templating import templates

router = APIRouter(tags=["scan"])


@router.post("/api/scan", status_code=202)
def start_scan(settings: SettingsDep, response: Response) -> dict:
    """Start a scan in the background. Returns 409 if one is already running."""
    if not scan_job.start(settings):
        response.status_code = 409
    return scan_state(scan_job)


@router.get("/api/scan")
def get_scan() -> dict:
    """Progress of the current or last scan."""
    return scan_state(scan_job)


@router.post("/partials/scan", response_class=HTMLResponse, include_in_schema=False)
def start_scan_partial(request: Request, settings: SettingsDep):
    scan_job.start(settings)
    return _render(request)


@router.get("/partials/scan", response_class=HTMLResponse, include_in_schema=False)
def scan_partial(request: Request, was_running: bool = False):
    response = _render(request)
    if was_running and not scan_job.running:
        # The scan just finished: reload the page so the dashboard shows the new numbers.
        reload_page(request, response)
    return response


def _render(request: Request):
    return templates.TemplateResponse(request, "partials/scan_status.html", {"job": scan_job})


def scan_state(job: ScanJob) -> dict:
    p = job.progress
    return {
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "total": p.total,
        "processed": p.processed,
        "added": p.added,
        "updated": p.updated,
        "unchanged": p.unchanged,
        "moved": p.moved,
        "removed": p.removed,
        "errors": p.errors,
        "current": p.current,
    }

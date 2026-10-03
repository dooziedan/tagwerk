"""FastAPI application: creates the app and registers pages and API routes."""

from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.config import Settings, get_settings

BASE_DIR = Path(__file__).parent
SettingsDep = Annotated[Settings, Depends(get_settings)]

app = FastAPI(title="Tagwerk", version=__version__)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Used by the Docker HEALTHCHECK (shown as healthy/unhealthy on Unraid)."""
    return {"status": "ok"}


@app.get("/api/status", tags=["system"])
def status(settings: SettingsDep) -> dict:
    """Basic info about the running instance and its mounted folders."""
    return {
        "version": __version__,
        "music_dir": str(settings.music_dir),
        "music_dir_found": settings.music_dir.is_dir(),
        "config_dir": str(settings.config_dir),
        "config_dir_writable": _is_writable(settings.config_dir),
    }


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request, settings: SettingsDep):
    return templates.TemplateResponse(request, "index.html", {"status": status(settings)})


def _is_writable(path: Path) -> bool:
    probe = path / ".write-test"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False

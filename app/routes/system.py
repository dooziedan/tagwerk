"""Health check and setup status."""

from pathlib import Path

from fastapi import APIRouter, Request

from app import __version__
from app.config import Settings, SettingsDep

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict[str, str]:
    """Used by the Docker HEALTHCHECK (shown as healthy/unhealthy on Unraid)."""
    return {"status": "ok"}


@router.get("/api/status")
def status(request: Request, settings: SettingsDep) -> dict:
    """Basic info about the running instance and its mounted folders."""
    return setup_status(request, settings)


def setup_status(request: Request, settings: Settings) -> dict:
    db_error = getattr(request.app.state, "db_error", None)
    music_found = settings.music_dir.is_dir()
    config_writable = _is_writable(settings.config_dir)
    return {
        "version": __version__,
        "music_dir": str(settings.music_dir),
        "music_dir_found": music_found,
        "config_dir": str(settings.config_dir),
        "config_dir_writable": config_writable,
        "database_ok": db_error is None,
        "database_error": db_error,
        "ok": music_found and config_writable and db_error is None,
    }


def _is_writable(path: Path) -> bool:
    probe = path / ".write-test"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False

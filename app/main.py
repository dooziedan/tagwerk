"""FastAPI application: creates the app, prepares the database and registers the routes."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import get_settings
from app.db import migrate
from app.routes import dashboard, fields, scan, settings, system

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Keep running even if the database can't be created, so the setup check can say why.
    app.state.db_error = None
    try:
        settings.config_dir.mkdir(parents=True, exist_ok=True)
        migrate(settings.database_url)
    except Exception as exc:
        log.exception("Database setup failed")
        app.state.db_error = f"{type(exc).__name__}: {exc}"
    yield


app = FastAPI(title="Tagwerk", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(system.router)
app.include_router(dashboard.router)
app.include_router(scan.router)
app.include_router(settings.router)
app.include_router(fields.router)

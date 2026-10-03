"""Database connection and migrations."""

from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Annotated

from alembic import command
from alembic.config import Config
from fastapi import Depends
from sqlalchemy import Engine, event
from sqlmodel import Session, create_engine

from app.config import SettingsDep

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


@cache
def get_engine(url: str) -> Engine:
    """One engine (connection pool) per database URL, shared by requests and jobs."""
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},  # the scan job runs in its own thread
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        # WAL lets the dashboard read while a scan is writing.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def migrate(url: str) -> None:
    """Bring the database schema up to date. Runs on every start."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def get_session(settings: SettingsDep) -> Iterator[Session]:
    with Session(get_engine(settings.database_url)) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]

"""Upgrading an old database through every migration, with data in it.

The owner's database was created by an early version and has rows in every table. Each migration
must keep them and fill new NOT NULL columns. This test starts with the first schema, upgrades
one step at a time and, after every step, puts a row into each table that is still empty (so
tables added later get rows too, without naming them here). At the end today's code reads the
upgraded database, and everything is downgraded again.
"""

from datetime import datetime

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, DateTime, Float, Integer, MetaData, create_engine, func, select
from sqlmodel import Session

from app import duplicates, preferences
from app.db import MIGRATIONS_DIR
from app.home import home_data
from app.models import Track
from app.stats import library_stats
from app.work import work_stats


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _value(column):
    """A plain value of the column's type. Text is "{}", which also reads as JSON."""
    if isinstance(column.type, Boolean):
        return False
    if isinstance(column.type, Integer):
        return 1  # also the id every foreign key points to
    if isinstance(column.type, Float):
        return 1.0
    if isinstance(column.type, DateTime):
        return datetime(2026, 10, 1, 12, 0)
    return "{}"


def _fill_empty_tables(engine) -> set[str]:
    meta = MetaData()
    meta.reflect(engine)
    filled = set()
    with engine.begin() as connection:
        for table in meta.sorted_tables:  # parents before the tables that point at them
            if table.name == "alembic_version":
                continue
            if connection.execute(select(func.count()).select_from(table)).scalar():
                continue
            connection.execute(table.insert().values({c.name: _value(c) for c in table.columns}))
            filled.add(table.name)
    return filled


def test_an_old_database_upgrades_through_every_migration(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    config = _config(url)
    revisions = [r.revision for r in ScriptDirectory.from_config(config).walk_revisions()][::-1]
    engine = create_engine(url)
    tables = set()
    for revision in revisions:
        command.upgrade(config, revision)
        tables |= _fill_empty_tables(engine)
    assert {"track", "rawtag", "changeset", "inboxtrack", "duplicatetrack"} <= tables

    meta = MetaData()
    meta.reflect(engine)
    with engine.connect() as connection:
        for name in tables:  # nothing was lost on the way
            assert connection.execute(select(func.count()).select_from(meta.tables[name])).scalar()

    with Session(engine) as session:
        track = session.get(Track, 1)
        assert track.path == "{}" and track.has_lyrics is False and track.scan_version == 0
        prefs = preferences.load(session)  # odd stored values fall back to defaults
        home_data(session)
        library_stats(session, prefs)
        work_stats(session)
        duplicates.load_groups(session)
    duplicates.refresh_library(engine, tmp_path)
    engine.dispose()

    command.downgrade(config, "base")
    meta = MetaData()
    meta.reflect(create_engine(url))
    assert set(meta.tables) == {"alembic_version"}

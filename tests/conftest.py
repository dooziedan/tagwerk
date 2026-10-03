import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import get_engine, migrate

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def music_dir(tmp_path) -> Path:
    """A small library: the fixture files arranged in artist/album folders."""
    root = tmp_path / "music"
    layout = {
        "Fixture Artist/Fixture Album": [
            "tagged.mp3",
            "tagged.flac",
            "tagged.wav",
            "tagged.aiff",
            "tagged.m4a",
        ],
        "Info Artist/Info Album": ["riff-info.wav"],
        "Unsorted": ["untagged.mp3", "discogs-ids.flac"],
    }
    for folder, names in layout.items():
        (root / folder).mkdir(parents=True)
        for name in names:
            shutil.copy(FIXTURES / name, root / folder / name)
    return root


@pytest.fixture
def settings(tmp_path, music_dir, monkeypatch) -> Settings:
    """App settings pointing at the temporary library and config folder."""
    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("MUSIC_DIR", str(music_dir))
    monkeypatch.setenv("CONFIG_DIR", str(config))
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def engine(settings):
    migrate(settings.database_url)
    engine = get_engine(settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def client(settings):
    from app.main import app

    with TestClient(app) as client:  # "with" runs startup, which migrates the database
        yield client

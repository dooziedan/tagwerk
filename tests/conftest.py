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
            "tagged.ogg",
            "tagged.opus",
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
    monkeypatch.setenv("IMPORT_DIR", str(tmp_path / "import"))  # created by tests that need it
    monkeypatch.setenv("ORIGINALS_DIR", str(tmp_path / "originals"))  # likewise
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
        # Most tests are about pages after the first start; the wizard has its own tests.
        prefs = client.get("/api/settings").json() | {"setup_done": True}
        client.put("/api/settings", json=prefs)
        yield client


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests never ask real online sources; tests of app/sources/ feed them saved answers."""
    from app.sources.base import Source, SourceError

    def no_network(self, url, params=None, headers=None):
        raise SourceError("offline during tests")

    monkeypatch.setattr(Source, "get_json", no_network)


# What the stand-in analysis "hears" (tests can change it); the real one is tested on its own.
FAKE_ANALYSIS = {
    "bpm": 87.0,
    "bpm_sure": False,
    "bpm_alternatives": [174.0],
    "key": "7A",
    "key_sure": True,
    "key_alternatives": [],
    "notes": ["All 3 tempo methods measured 87 BPM"],
    "votes": {},
    "seconds": 20.0,
    "error": None,
    "version": 1,
}


@pytest.fixture(autouse=True)
def quick_analysis(monkeypatch):
    """Inbox checks start audio analyses in the background; in tests they answer at once
    instead of running Essentia in a separate process for every file."""
    from app import analysis
    from app.audio_analysis import ANALYSIS_VERSION

    monkeypatch.setattr(
        analysis, "run_analysis", lambda path: FAKE_ANALYSIS | {"version": ANALYSIS_VERSION}
    )

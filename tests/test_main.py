import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


@pytest.fixture
def client(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    app.dependency_overrides[get_settings] = lambda: Settings(music_dir=music, config_dir=tmp_path)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_status_reports_mounted_folders(client):
    data = client.get("/api/status").json()
    assert data["music_dir_found"] is True
    assert data["config_dir_writable"] is True


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Tagwerk is running" in response.text

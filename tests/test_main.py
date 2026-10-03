import shutil

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlmodel import SQLModel

from app.jobs import scan_job


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_status_reports_mounted_folders(client):
    data = client.get("/api/status").json()
    assert data["music_dir_found"] is True
    assert data["config_dir_writable"] is True
    assert data["database_ok"] is True


def test_dashboard_before_first_scan(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No tracks yet" in response.text
    assert "Setup problem" not in response.text


def test_scan_then_dashboard(client):
    response = client.post("/api/scan")
    assert response.status_code == 202
    scan_job.wait(timeout=30)
    assert client.get("/api/scan").json()["status"] == "done"

    stats = client.get("/api/stats").json()
    assert stats["tracks"] == 8

    page = client.get("/").text
    assert "Formats" in page and "Missing tags" in page
    assert "M4A" in page


def test_missing_music_folder_shows_setup_problem(client, music_dir):
    shutil.rmtree(music_dir)
    page = client.get("/").text
    assert "Setup problem" in page
    assert "Music library" in page


def test_migrations_match_models(engine):
    """Fails if a model was changed without adding a migration."""
    with engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), SQLModel.metadata)
    assert diff == []

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
    assert stats["tracks"] == 10

    page = client.get("/").text
    assert "Formats" in page and "Missing tags" in page
    assert "M4A" in page and "OPUS" in page
    assert "Decades" in page  # Collector is the default mode


def test_settings_api(client):
    assert client.get("/api/settings").json() == {
        "mode": "collector",
        "key_notation": "camelot",
        "show_musicbrainz": False,
    }
    saved = client.put(
        "/api/settings", json={"mode": "dj", "key_notation": "musical", "show_musicbrainz": True}
    ).json()
    assert saved["mode"] == "dj"
    assert client.get("/api/settings").json() == saved


def test_settings_form_and_unknown_values(client):
    response = client.post(
        "/settings",
        content="mode=dj&key_notation=bogus",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    prefs = client.get("/api/settings").json()
    assert prefs["mode"] == "dj"
    assert prefs["key_notation"] == "camelot"  # unknown value falls back to the default
    assert prefs["show_musicbrainz"] is False  # unchecked box
    assert "Settings" in client.get("/settings").text


def test_mode_switch_shows_dj_dashboard(client):
    client.post("/api/scan")
    scan_job.wait(timeout=30)
    client.put("/api/settings", json={"mode": "dj", "key_notation": "openkey"})
    page = client.get("/").text
    assert "DJ library" in page
    assert "Tempo" in page and "Keys" in page
    assert ">1m<" in page  # Am shown in Open Key notation
    assert "Decades" not in page

    response = client.post(
        "/settings/mode",
        content="mode=collector",
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Decades" in client.get("/").text


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

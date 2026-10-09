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


def test_home_before_first_scan(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "No tracks yet" in response.text
    assert "Setup problem" not in response.text


def test_scan_then_statistics(client):
    response = client.post("/api/scan")
    assert response.status_code == 202
    scan_job.wait(timeout=30)
    assert client.get("/api/scan").json()["status"] == "done"

    stats = client.get("/api/stats").json()
    assert stats["tracks"] == 10

    page = client.get("/stats").text
    assert "Formats" in page and "Missing tags" in page
    assert "M4A" in page and "OPUS" in page
    assert "Tempo" in page and "Decades" not in page  # made for DJs (ADR 0024)


def test_settings_api(client):
    assert client.get("/api/settings").json() == {
        "key_notation": "camelot",
        "show_musicbrainz": False,
        "effects": "full",
        "backup_confirmed": False,
        "setup_done": True,  # set by the client fixture (tests/conftest.py)
        "folder_layout": "genre",
        "folder_pattern": "{genre}",
        "genre_folders": [],
        "kept_unsorted": [],
        "automation": "ask",
        "remove_traktor_on_import": False,
        "genre_map": "",
        "online_sources": ["acoustid", "musicbrainz", "discogs", "deezer", "itunes"],
        "rename_on_final": False,
        "filename_pattern": "{artist} - {title}",
    }
    saved = client.put(
        "/api/settings", json={"mode": "dj", "key_notation": "musical", "show_musicbrainz": True}
    ).json()
    assert saved["key_notation"] == "musical" and "mode" not in saved  # unknown names ignored
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
    assert prefs["key_notation"] == "camelot"  # unknown value falls back to the default
    assert prefs["show_musicbrainz"] is False  # unchecked box
    assert "Settings" in client.get("/settings").text


def test_statistics_are_made_for_djs(client):
    client.post("/api/scan")
    scan_job.wait(timeout=30)
    client.put("/api/settings", json={"key_notation": "openkey"})
    page = client.get("/stats").text
    assert "<h1>Statistics</h1>" in page
    assert "Tempo" in page and "Keys" in page
    assert ">1m<" in page  # Am shown in Open Key notation
    assert "Decades" not in page and "Collector" not in page


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


def test_the_menu_shows_where_you_are(client):
    """The sidebar marks the page you're on (Home on the start page, Tracks on a track page)."""
    page = client.get("/").text
    assert '<a class="nav" href="/" aria-current="page">' in page
    assert "<title>Home · Tagwerk</title>" in page
    assert '<a class="nav" href="/stats" aria-current="page">' in client.get("/stats").text
    tracks = client.get("/tracks").text
    assert '<a class="nav" href="/tracks" aria-current="page">' in tracks
    assert '<a class="nav" href="/" aria-current="page">' not in tracks
    assert '<a class="nav" href="/settings" aria-current="page">' in client.get("/settings").text


def test_home_shows_what_needs_you_and_recent_tracks(client):
    client.post("/api/scan")
    scan_job.wait(timeout=30)
    page = client.get("/").text
    assert "Waiting for you" in page and "Worth a look" in page
    assert "Recently added" in page and "Silent Track" in page  # the fixtures' title
    assert "tracks not set-ready yet" in page
    data = client.get("/api/home").json()
    assert data["tracks"] == 10 and len(data["recent"]) == 10
    assert data["added_this_month"] == 10  # fixture files are fresh copies


def test_heat_map_axes(client):
    client.post("/api/scan")
    scan_job.wait(timeout=30)
    page = client.get("/stats?rows=year&cols=genre").text
    assert 'aria-label="Release year by Genre: number of tracks"' in page
    assert "/tracks?genre=Electronic&amp;year=2021" in page
    grid = client.get("/api/stats/heatmap", params={"rows": "key", "cols": "key"}).json()
    assert (grid["rows"], grid["cols"]) == ("key", "tempo")  # the same axis twice isn't useful


def test_the_unraid_template_has_every_setting():
    """A new setting in app/config.py needs its field in the Unraid template too."""
    import xml.etree.ElementTree as ET
    from pathlib import Path

    from app.config import Settings

    template = Path(__file__).parent.parent / "unraid" / "tagwerk.xml"
    targets = {c.get("Target") for c in ET.parse(template).getroot().iter("Config")}
    for name in Settings.model_fields:
        if name.endswith("_dir"):  # folders are paths: /music, /import, /originals, /config
            assert "/" + name.removesuffix("_dir") in targets, name
        else:
            assert name.upper() in targets, name

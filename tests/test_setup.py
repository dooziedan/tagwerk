# ruff: noqa: E501  (the step table reads best one step per line)
import shutil

from app.jobs import scan_job
from tests.conftest import FIXTURES


def prefs(client):
    return client.get("/api/settings").json()


def test_first_start_leads_to_the_wizard_and_skip_ends_it(client):
    client.put("/api/settings", json={"setup_done": False})
    first = client.get("/", follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/setup"
    assert "Welcome to Tagwerk" in client.get("/setup").text
    client.post("/setup/skip")
    assert prefs(client)["setup_done"] is True
    assert client.get("/", follow_redirects=False).status_code == 200


def test_walk_through_every_step(client):
    client.put("/api/settings", json={"setup_done": False})
    steps = [
        ("welcome", {}),
        ("style", {"mode": "dj", "key_notation": "musical"}),
        ("folders", {"folder_layout": "genre", "genre_folders": ["House"], "more_genres": "Breaks, Disco"}),
        ("automation", {"automation": "auto"}),
        ("final", {"rename_on_final": "on", "filename_pattern": "{artist} - {title} [{bpm} {key}]"}),
    ]  # fmt: skip
    following = ["style", "folders", "automation", "final", "done"]
    for (step, data), after in zip(steps, following, strict=True):
        response = client.post(f"/setup/{step}", data=data, follow_redirects=False)
        assert response.headers["location"] == f"/setup?step={after}"
    summary = client.get("/setup?step=done").text
    assert "House, Breaks, Disco, others to _Unsorted" in summary
    done = client.post("/setup/done", data={"backup": "on"}, follow_redirects=False)
    assert done.headers["location"] == "/"
    p = prefs(client)
    assert (p["mode"], p["key_notation"], p["automation"]) == ("dj", "musical", "auto")
    assert p["genre_folders"] == ["House", "Breaks", "Disco"]
    assert p["rename_on_final"] and p["filename_pattern"] == "{artist} - {title} [{bpm} {key}]"
    assert p["setup_done"] and p["backup_confirmed"]


def test_wrong_patterns_are_explained(client):
    bad = client.post("/setup/final", data={"filename_pattern": "{artist} - {titel}"})
    assert bad.status_code == 422 and "Unknown: {titel}" in bad.text
    bad = client.post(
        "/setup/folders", data={"folder_layout": "custom", "folder_pattern": "{title}"}
    )
    assert bad.status_code == 422 and "Unknown: {title}" in bad.text
    assert prefs(client)["filename_pattern"] == "{artist} - {title}"  # nothing saved


def test_live_preview_uses_real_tracks(client):
    client.post("/api/scan")
    scan_job.wait(30)
    page = client.get(
        "/setup/preview", params={"kind": "file", "filename_pattern": "{title} ({bpm})"}
    )
    assert "Silent Track (126)." in page.text  # extension of each example
    page = client.get("/setup/preview", params={"kind": "folder", "folder_layout": "artist"})
    assert "Artist One/" in page.text  # the track artist, not the album artist
    page = client.get("/setup/preview", params={"kind": "file", "filename_pattern": "{nope}"})
    assert "Unknown: {nope}" in page.text


def test_settings_sections_change_the_same_choices(client):
    page = client.get("/settings").text
    for section in ('id="import"', 'id="genres"', 'id="final"', 'id="setup"'):
        assert section in page
    client.post("/settings/choices/import", data={"folder_layout": "date", "automation": "auto"})
    client.post("/settings/choices/final", data={"filename_pattern": "{bpm} - {title}"})
    p = prefs(client)
    assert (p["folder_layout"], p["automation"], p["filename_pattern"]) == (
        "date",
        "auto",
        "{bpm} - {title}",
    )
    assert p["rename_on_final"] is False  # unticked switch

    bad = client.post("/settings/genres", data={"genre_map": "House > Deep House\njust words"})
    assert bad.status_code == 422 and "Line 2" in bad.text
    client.post("/settings/genres", data={"genre_map": "Breaks = Breakbeat"})
    assert prefs(client)["genre_map"] == "Breaks = Breakbeat"
    client.post("/settings/genres", data={"reset": "1"})
    assert prefs(client)["genre_map"] == ""

    again = client.post("/settings/setup-again", follow_redirects=False)
    assert again.headers["location"] == "/setup" and prefs(client)["setup_done"] is False


def test_import_uses_the_chosen_folder_layout(client, settings):
    from app.jobs import inbox_job, write_job

    client.put("/api/settings", json={"folder_layout": "artist"})
    settings.import_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.flac", settings.import_dir / "x.flac")
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    track = client.get("/api/inbox").json()[0]["id"]
    assert "On import goes to <code>Artist One/x.flac" in client.get(f"/inbox/{track}").text
    client.post("/inbox/import", data={"ids": [str(track)]})
    write_job.wait(30)
    assert (settings.music_dir / "Artist One" / "x.flac").exists()  # the filename never changes

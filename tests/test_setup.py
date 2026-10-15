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
        ("style", {"key_notation": "musical"}),
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
    assert (p["key_notation"], p["automation"]) == ("musical", "auto")
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
    # An old tempo line typed into the map goes to the BPM ranges.
    client.post("/settings/genres", data={"genre_map": "Breaks = Breakbeat\nBreaks: 125-140 BPM"})
    p = prefs(client)
    assert p["genre_map"].strip() == "Breaks = Breakbeat" and p["bpm_ranges"]["Breaks"] == [
        125,
        140,
    ]

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


def bpm_form(client) -> dict:
    """The BPM ranges form as the page shows it: genre_0, low_0, high_0, …"""
    import re

    page = client.get("/settings").text
    section = page[page.index('action="/settings/bpm"') :]
    section = section[: section.index("</form>")]
    return dict(re.findall(r'name="((?:genre|low|high)_\d+)" value="([^"]*)"', section))


def test_bpm_ranges_in_settings(client):
    page = client.get("/settings").text
    assert 'id="bpm"' in page and "BPM ranges" in page and "19 genres · built-in" in page
    assert "with Liquid, Liquid Funk, Liquid Drum &amp; Bass +6" in page  # subgenres share it
    # Saved in the background: only the section, the overview and the message are replaced.
    assert 'hx-post="/settings/bpm" hx-target="#bpm" hx-select="#bpm"' in page
    assert 'id="settings-nav"' in page and 'id="settings-toasts"' in page
    form = bpm_form(client)
    dubstep = next(k.split("_")[1] for k, v in form.items() if v == "Dubstep")
    assert (form[f"low_{dubstep}"], form[f"high_{dubstep}"]) == ("135", "150")

    # Change one (half time), add one, remove one: all in one save.
    form[f"low_{dubstep}"], form[f"high_{dubstep}"] = "70", "75"
    juke = next(k.split("_")[1] for k, v in form.items() if v == "Juke")
    saved = client.post(
        "/settings/bpm",
        data={**form, "genre_new": "Breaks", "low_new": "125", "high_new": "140", "remove": juke},
        follow_redirects=False,
    )
    assert saved.headers["location"] == "/settings?saved=bpm"
    ranges = prefs(client)["bpm_ranges"]
    assert ranges["Dubstep"] == [70, 75] and ranges["Breaks"] == [125, 140]
    assert "Juke" not in ranges and len(ranges) == 19
    assert "your own" in client.get("/settings").text

    # Mistakes come back with the rows as typed and a message.
    bad = client.post("/settings/bpm", data={"genre_0": "House", "low_0": "fast", "high_0": "130"})
    assert bad.status_code == 422 and "House: enter the lowest and the highest BPM" in bad.text
    assert 'value="fast"' in bad.text
    twice = client.post(
        "/settings/bpm",
        data={"genre_0": "House", "low_0": "120", "high_0": "130", "genre_1": "house",
              "low_1": "110", "high_1": "120"},
    )  # fmt: skip
    assert twice.status_code == 422 and "house is listed twice" in twice.text
    wide = client.post("/settings/bpm", data={"genre_0": "Ambient", "low_0": "20", "high_0": "60"})
    assert wide.status_code == 422 and "from 40 to 300" in wide.text
    assert prefs(client)["bpm_ranges"]["Dubstep"] == [70, 75]  # nothing saved

    client.post("/settings/bpm", data={"reset": "1"})
    assert prefs(client)["bpm_ranges"] is None


def test_new_bpm_ranges_decide_the_library_bpm_again(client, engine):
    """After saving, the library's BPM decisions follow the new ranges right away."""
    import json

    from sqlmodel import Session

    from app.models import LibraryAnalysis, Track

    with Session(engine) as session:
        track = Track(
            path="d.mp3",
            format="mp3",
            size=1,
            mtime=0,
            title="T",
            artist="A",
            genre="Dubstep",
            bpm=None,
        )
        session.add(track)
        session.commit()
        detail = {"bpm_alternatives": [70.0], "key_alternatives": []}
        session.add(LibraryAnalysis(track_id=track.id, bpm=140.0, bpm_sure=True,
                                    detail=json.dumps(detail)))  # fmt: skip
        session.commit()
        track_id = track.id
    client.post("/settings/bpm", data={"genre_0": "Dubstep", "low_0": "70", "high_0": "75"})
    with Session(engine) as session:
        assert session.get(LibraryAnalysis, track_id).decided_bpm == 70

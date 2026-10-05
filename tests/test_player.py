import json
import shutil

import pytest
from sqlmodel import Session, select

from app.inbox import scan_inbox
from app.models import InboxTrack, Track
from app.navigation import reload_page
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"


@pytest.fixture
def library(engine, settings):
    scan_library(engine, settings.music_dir, ScanProgress())


def track_id(engine, name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(Track).where(Track.path == f"{ALBUM}/{name}")).one().id


def test_audio_is_served_with_range_requests(client, engine, library, settings):
    tid = track_id(engine, "tagged.mp3")
    whole = client.get(f"/tracks/{tid}/audio")
    assert whole.status_code == 200
    assert whole.headers["content-type"] == "audio/mpeg"
    assert whole.content == (settings.music_dir / ALBUM / "tagged.mp3").read_bytes()
    part = client.get(f"/tracks/{tid}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert len(part.content) == 100


def test_unknown_track_is_404(client, library):
    assert client.get("/tracks/9999/audio").status_code == 404
    assert client.get("/inbox/9999/audio").status_code == 404


def test_path_outside_the_library_is_refused(client, engine, library):
    tid = track_id(engine, "tagged.mp3")
    with Session(engine) as session:
        track = session.get(Track, tid)
        track.path = "../config/tagwerk.db"
        session.add(track)
        session.commit()
    assert client.get(f"/tracks/{tid}/audio").status_code == 404


def test_inbox_audio(client, engine, settings):
    settings.import_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.flac", settings.import_dir / "a.flac")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        tid = session.exec(select(InboxTrack)).one().id
    response = client.get(f"/inbox/{tid}/audio")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/flac"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_aiff_is_converted_to_mp3(client, engine, library):
    tid = track_id(engine, "tagged.aiff")
    response = client.get(f"/tracks/{tid}/audio.mp3?start=0")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert len(response.content) > 0


def test_pages_have_play_buttons_and_the_bar(client, engine, library):
    tid = track_id(engine, "tagged.mp3")
    assert f'data-play="/tracks/{tid}/audio"' in client.get("/tracks").text
    page = client.get(f"/tracks/{tid}").text
    assert f'data-play="/tracks/{tid}/audio"' in page
    assert 'id="player"' in page and 'hx-boost="true"' in page
    assert 'id="player-mute"' in page and 'id="player-volume"' in page
    assert page.index('id="player"') > page.index("</footer>")  # outside #page


def test_reload_page_swaps_only_the_page_part():
    from starlette.requests import Request
    from starlette.responses import Response

    def request(headers):
        return Request({"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers]})

    response = Response()
    reload_page(request([("hx-current-url", "http://x/tracks?q=a")]), response)
    assert '"path": "/tracks?q=a"' in response.headers["hx-location"]
    assert '"select": "#page"' in response.headers["hx-location"]

    response = Response()
    reload_page(request([]), response)
    assert response.headers["hx-refresh"] == "true"


def test_reload_page_replaces_the_address_and_drops_parameters():
    from starlette.requests import Request
    from starlette.responses import Response

    request = Request(
        {"type": "http", "headers": [(b"hx-current-url", b"http://x/tracks/3?looking=1&back=%2F")]}
    )
    response = Response()
    reload_page(request, response, drop=("looking",))
    location = json.loads(response.headers["hx-location"])
    assert location["path"] == location["replace"] == "/tracks/3?back=%2F"
    assert location["push"] is False  # Back doesn't step through the same page


def test_lookup_status_waits_then_shows_the_page_again(client, engine, library, monkeypatch):
    from app.jobs import identify_job

    tid = track_id(engine, "tagged.mp3")
    headers = {"HX-Request": "true", "HX-Current-URL": f"http://x/tracks/{tid}?looking=1"}
    monkeypatch.setattr(identify_job, "queued", lambda track_id, library=False: True)
    waiting = client.get(f"/tracks/{tid}/lookup-status", headers=headers)
    assert waiting.status_code == 204 and "hx-location" not in waiting.headers
    assert 'lookup-status" hx-trigger="every 2s"' in client.get(f"/tracks/{tid}").text

    monkeypatch.setattr(identify_job, "queued", lambda track_id, library=False: False)
    done = client.get(f"/tracks/{tid}/lookup-status", headers=headers)
    assert json.loads(done.headers["hx-location"])["path"] == f"/tracks/{tid}"
    assert "lookup-status" not in client.get(f"/tracks/{tid}").text  # no more polling


def test_inbox_lookup_status(client, engine, settings, monkeypatch):
    from app.jobs import identify_job

    settings.import_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.flac", settings.import_dir / "a.flac")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        tid = session.exec(select(InboxTrack)).one().id
    headers = {"HX-Request": "true", "HX-Current-URL": f"http://x/inbox/{tid}"}
    monkeypatch.setattr(identify_job, "queued", lambda track_id, library=False: True)
    assert "hx-location" not in client.get(f"/inbox/{tid}/lookup-status", headers=headers).headers
    monkeypatch.setattr(identify_job, "queued", lambda track_id, library=False: False)
    assert "hx-location" in client.get(f"/inbox/{tid}/lookup-status", headers=headers).headers

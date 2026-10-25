"""The Releasomat page (ADR 0044, step 3): the area's own list, read-only, with Releasomat's
playlists when it answers and "in your library" / "better sound" from Tagwerk's own rules."""

import shutil
from dataclasses import replace

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from app import area, preferences, releasomat
from app.config import get_settings
from app.db import get_engine
from app.jobs import scan_job
from app.models import ReleasomatFile, Track
from app.routes import releasomat as page
from tests.conftest import FIXTURES
from tests.fake_releasomat import KEY, URL, FakeReleasomat

AREA = "Releasomat"
BETTER = "A/Silent.flac"  # lossless; the library copy is an MP3
NEW = "B/promo.mp3"  # untagged: Releasomat knows what it is
SAME = "C/same.mp3"  # the library's very file
BROKEN = "D/broken.mp3"


@pytest.fixture
def music_dir(tmp_path):
    """A one-track library (an MP3) and four Releasomat downloads."""
    root = tmp_path / "music"
    (root / "House").mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.mp3", root / "House" / "Artist One - Silent Track.mp3")
    for rel, name in ((BETTER, "tagged.flac"), (NEW, "untagged.mp3"), (SAME, "tagged.mp3")):
        (root / AREA / rel).parent.mkdir(parents=True)
        shutil.copy(FIXTURES / name, root / AREA / rel)
    (root / AREA / BROKEN).parent.mkdir(parents=True)
    (root / AREA / BROKEN).write_bytes(b"not audio")
    return root


def releasomat_files(music_dir) -> dict:
    """What Releasomat answers for these four files."""
    weekly = {"id": 1, "name": "Weekly Exploration", "url": f"{URL}/playlists/1"}
    top = {"id": 2, "name": "Beatport Top 100", "url": f"{URL}/playlists/2"}

    def item(i, rel, artist, title, lists, **wanted):
        size = (music_dir / AREA / rel).stat().st_size
        return {"id": i, "path": rel, "size": size, "downloaded_at": f"2026-10-2{i}T09:00:00Z",
                "downloader": "slskd", "format": rel.rsplit(".", 1)[-1], "bitrate": None,
                "wanted": {"artist": artist, "title": title, **wanted},
                "playlists": lists}  # fmt: skip

    return {"integration_api": 1, "folder": AREA, "files": [
        item(1, BETTER, "Artist One", "Silent Track", [weekly, top]),
        item(2, NEW, "Someone", "Promo", [top], bpm=174.0, key="A Minor"),
        item(3, SAME, "Artist One", "Silent Track", [weekly]),
        item(4, BROKEN, "Nobody", "Broken", []),
    ]}  # fmt: skip


@pytest.fixture
def kept_out(client, engine, settings, music_dir, monkeypatch):
    """Releasomat set up and answering; its folder kept out of the library and read."""
    fake = FakeReleasomat(files=releasomat_files(music_dir))
    monkeypatch.setattr(releasomat.urllib.request, "urlopen", fake)
    monkeypatch.setenv("RELEASOMAT_URL", URL)
    monkeypatch.setenv("RELEASOMAT_API_KEY", KEY)
    monkeypatch.setenv("RELEASOMAT_FOLDER", AREA)
    get_settings.cache_clear()
    releasomat.forget_files()
    page._last_check = 0.0
    assert client.post("/api/releasomat/area", json={"folder": AREA}).json()["scan_started"]
    scan_job.wait()
    yield fake
    releasomat.forget_files()


def rows(client, **params) -> dict:
    return client.get("/api/releasomat/files", params=params).json()


def test_the_scan_reads_the_area_into_its_own_table(engine, kept_out):
    with Session(engine) as session:
        assert [t.path for t in session.exec(select(Track))] == [
            "House/Artist One - Silent Track.mp3"
        ]
        files = {f.path: f for f in session.exec(select(ReleasomatFile))}
    assert set(files) == {BETTER, NEW, SAME, BROKEN}
    assert files[BETTER].format == "flac" and files[BETTER].title == "Silent Track"
    assert files[BROKEN].error and files[NEW].title is None


def test_the_page_lists_the_files_with_playlists_and_library_copies(client, kept_out):
    data = rows(client)
    assert data["counts"] == {"all": 4, "new": 2, "library": 1, "better": 1, "low": 2}
    by_path = {f["path"]: f for f in data["files"]}
    assert [f["path"] for f in data["files"]] == [BROKEN, SAME, NEW, BETTER]  # newest first
    assert by_path[BETTER]["better_sound"]["why"] == "lossless instead of lossy"
    assert by_path[SAME]["in_library"][0]["why"] == "identical file"
    new = by_path[NEW]
    assert (new["artist"], new["title"]) == ("Someone", "Promo")  # what Releasomat wanted
    assert (new["bpm"], new["key"], new["low_quality"]) == (174.0, "8A", True)
    assert [p["name"] for p in new["playlists"]] == ["Beatport Top 100"]
    assert by_path[BROKEN]["error"]

    html = client.get("/releasomat").text
    assert "Discovery area · not in your library" in html
    assert "Better sound: FLAC" in html and "In your library · identical file" in html
    assert "Weekly Exploration" in html and f'href="{URL}/playlists/2"' in html
    assert "174 BPM" in html and "(source)" in html
    assert 'href="/releasomat"' in client.get("/").text  # in the menu


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"show": "new"}, {NEW, BROKEN}),
        ({"show": "library"}, {SAME}),
        ({"show": "better"}, {BETTER}),
        ({"show": "low"}, {NEW, SAME}),
        ({"playlist": 1}, {BETTER, SAME}),
        ({"q": "promo"}, {NEW}),
        ({"q": "someone", "show": "low"}, {NEW}),
    ],
)
def test_tabs_playlists_and_search(client, kept_out, params, expected):
    assert {f["path"] for f in rows(client, **params)["files"]} == expected


def test_paging(client, kept_out, monkeypatch):
    monkeypatch.setattr(page, "PAGE_SIZE", 3)
    first, second = rows(client), rows(client, page=2)
    assert (first["pages"], len(first["files"]), len(second["files"])) == (2, 3, 1)
    html = client.get("/releasomat?show=all&q=&page=1").text
    assert 'href="/releasomat?page=2"' in html


def test_the_page_works_while_releasomat_is_down(client, kept_out):
    kept_out.answers["files"] = 503
    releasomat.forget_files()
    html = client.get("/releasomat").text
    assert "Releasomat answered: error 503" in html and "without their playlists" in html
    data = rows(client)
    assert data["releasomat"]["answers"] is False and len(data["files"]) == 4
    assert all(f["playlists"] == [] for f in data["files"])


def test_releasomat_is_asked_once_a_minute(client, kept_out):
    for _ in range(3):
        rows(client)
    assert kept_out.calls().count("files") == 1


def test_new_and_changed_files_are_read_and_gone_ones_forgotten(client, engine, settings,
                                                                 kept_out, music_dir):  # fmt: skip
    (music_dir / AREA / NEW).unlink()
    (music_dir / AREA / "E").mkdir()
    shutil.copy(FIXTURES / "tagged.opus", music_dir / AREA / "E" / "new.opus")
    progress = area.sync(engine, settings)
    assert (progress.added, progress.removed, progress.unchanged) == (1, 1, 3)
    assert area.sync(engine, settings).unchanged == 4  # nothing read again


def test_the_folder_check_without_a_kept_out_folder(client, engine, monkeypatch):
    monkeypatch.setenv("RELEASOMAT_FOLDER", AREA)
    get_settings.cache_clear()
    html = client.get("/releasomat").text
    assert "still part of your library" in html and "/settings#releasomat" in html
    with Session(engine) as session:
        assert not session.exec(select(ReleasomatFile)).all()


def test_without_releasomat_nothing_mentions_it(client):
    assert "/releasomat" not in client.get("/").text
    assert "isn't set up" in client.get("/releasomat").text


def test_treating_the_folder_as_library_forgets_its_list(client, engine, kept_out):
    client.delete("/api/releasomat/area")
    scan_job.wait()
    with Session(engine) as session:
        assert not session.exec(select(ReleasomatFile)).all()
        assert len(session.exec(select(Track)).all()) == 5  # the downloads are library again


def test_area_files_play_but_nothing_outside_the_area(client, engine, kept_out):
    with Session(engine) as session:
        flac = session.exec(select(ReleasomatFile).where(ReleasomatFile.path == BETTER)).one()
        flac.path = "../House/Artist One - Silent Track.mp3"  # a row pointing outside
        session.add(flac)
        session.commit()
        outside = flac.id
        same = session.exec(select(ReleasomatFile).where(ReleasomatFile.path == SAME)).one().id
    assert client.get(f"/releasomat/{same}/audio").status_code == 200
    assert client.get(f"/releasomat/{outside}/audio").status_code == 404
    assert client.get(f"/releasomat/{same}/cover").status_code == 200


def test_the_page_asks_the_database_as_often_for_4_files_as_for_12(
    client, engine, settings, kept_out, music_dir
):
    def queries() -> int:
        asked = 0

        def count(*args) -> None:
            nonlocal asked
            asked += 1

        event.listen(get_engine(settings.database_url), "before_cursor_execute", count)
        try:
            assert client.get("/releasomat").status_code == 200
        finally:
            event.remove(get_engine(settings.database_url), "before_cursor_execute", count)
        return asked

    page._last_check = float("inf")  # no folder check while counting
    before = queries()
    for i in range(8):
        shutil.copy(FIXTURES / "untagged.mp3", music_dir / AREA / "B" / f"more {i}.mp3")
    area.sync(engine, settings)
    assert queries() == before


def test_no_area_rows_while_prefs_say_nothing_is_kept_out(engine, settings):
    with Session(engine) as session:
        prefs = preferences.load(session)
        preferences.save(session, replace(prefs, releasomat_area=""))
    assert area.sync(engine, settings).total == 0


def test_downloads_you_already_have_are_flagged_as_a_possible_releasomat_bug(client, kept_out):
    """Releasomat links library songs instead of downloading them (owner, 2026-10-25)."""
    for show in ("library", "better"):
        assert (
            "Releasomat shouldn't download songs you already have"
            in client.get(f"/releasomat?show={show}").text
        )
    assert "shouldn't download songs" not in client.get("/releasomat?show=new").text
    assert "Releasomat shouldn't have downloaded it" in client.get("/releasomat").text

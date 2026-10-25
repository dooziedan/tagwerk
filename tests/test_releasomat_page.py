"""The Releasomat page (ADR 0044, step 3): the area's own list, read-only, with Releasomat's
playlists when it answers and "in your library" / "better sound" from Tagwerk's own rules."""

import shutil
from dataclasses import replace

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from app import area, preferences, releasomat
from app import models as page_models
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
    """Releasomat links library songs instead of downloading them (owner, 2026-10-25). It keeps
    using a download it already has, so the notice says how to switch to the library copy."""
    for show in ("library", "better"):
        page = client.get(f"/releasomat?show={show}").text
        assert "Releasomat shouldn't download songs you already have" in page
        assert "keeps using its own download as long as the file is here" in page
        assert "To use your copy instead" in page
    assert "shouldn't download songs" not in client.get("/releasomat?show=new").text
    assert "Releasomat shouldn't have downloaded it" in client.get("/releasomat").text


# --- Delete (step 4) ------------------------------------------------------------------------


def ids_of(engine, *paths) -> list[int]:
    with Session(engine) as session:
        rows = session.exec(select(ReleasomatFile).where(ReleasomatFile.path.in_(paths)))
        return [r.id for r in rows]


@pytest.fixture
def releasomat_deletes(kept_out, music_dir, monkeypatch):
    """Releasomat's side of delete: it removes the files (with the size check). Tagwerk itself
    must never remove a file in the area: any unlink there fails the test."""
    import os
    from pathlib import Path

    real_unlink = os.unlink
    area_root = (music_dir / AREA).resolve()
    releasomat_side = False  # True while the fake plays Releasomat deleting a file

    def guarded(path, *args, **kwargs):
        if not releasomat_side and Path(path).resolve().is_relative_to(area_root):
            raise AssertionError(f"Tagwerk removed {path}")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", guarded)
    monkeypatch.setattr(os, "remove", guarded)
    monkeypatch.setattr(os, "unlink", guarded)

    def delete(body):
        nonlocal releasomat_side
        answers = []
        for ref in body["files"]:
            target = area_root / ref["path"]
            if ref.get("size") != target.stat().st_size:
                answers.append({"asked": ref["path"], "ok": False, "reason": "size differs"})
                continue
            releasomat_side = True
            target.unlink()  # Releasomat's own owner-delete
            releasomat_side = False
            answers.append({"asked": ref["path"], "ok": True, "changed": True, "id": ref.get("id"),
                            "path": ref["path"], "status": "disliked"})  # fmt: skip
        return {"integration_api": 1, "files": answers}

    kept_out.answers["delete"] = delete
    return kept_out


def test_delete_asks_releasomat_and_the_file_leaves_the_list(client, engine, music_dir,
                                                             releasomat_deletes):  # fmt: skip
    ids = ids_of(engine, NEW, SAME)
    answer = client.post("/api/releasomat/delete", json={"ids": ids}).json()
    assert answer == {"files": [{"path": NEW, "deleted": True, "reason": None},
                                {"path": SAME, "deleted": True, "reason": None}]}  # fmt: skip
    [sent] = releasomat_deletes.sent("delete")
    assert sent["files"] == [
        {"path": NEW, "size": (FIXTURES / "untagged.mp3").stat().st_size, "id": 2},
        {"path": SAME, "size": (FIXTURES / "tagged.mp3").stat().st_size, "id": 3},
    ]
    assert {f["path"] for f in rows(client)["files"]} == {BETTER, BROKEN}
    assert (music_dir / "House" / "Artist One - Silent Track.mp3").exists()  # library untouched


def test_the_page_confirms_and_reports(client, engine, releasomat_deletes):
    html = client.get("/releasomat").text
    assert (
        "Releasomat deletes “Someone – Promo” and won't download it again. Still in: Beatport"
        in html
    )
    [one] = ids_of(engine, NEW)
    page = client.post("/releasomat/delete", data={"one": one, "back": "/releasomat?show=new"})
    assert page.url.path == "/releasomat" and "show=new" in str(page.url)
    assert "Releasomat deleted 1 file" in page.text and "Don't like" in page.text


def test_a_refusal_changes_nothing_and_says_why(client, engine, music_dir, releasomat_deletes):
    adopted = "Tagwerk adopted this file; it isn't Releasomat's now."
    releasomat_deletes.answers["delete"] = {
        "integration_api": 1,
        "files": [{"asked": NEW, "ok": False, "reason": adopted}],
    }
    page = client.post("/releasomat/delete", data={"ids": ids_of(engine, NEW)})
    assert "Tagwerk adopted this file" in page.text and (music_dir / AREA / NEW).exists()
    assert NEW in {f["path"] for f in rows(client)["files"]}


def test_yes_but_still_there_keeps_the_row(client, engine, kept_out, music_dir):
    answer = client.post("/api/releasomat/delete", json={"ids": ids_of(engine, NEW)}).json()
    assert answer["files"][0]["reason"] == "Releasomat said yes, but the file is still there."
    assert NEW in {f["path"] for f in rows(client)["files"]}


def test_a_changed_file_isnt_sent(client, engine, music_dir, releasomat_deletes):
    with open(music_dir / AREA / NEW, "ab") as f:
        f.write(b"more")
    answer = client.post("/api/releasomat/delete", json={"ids": ids_of(engine, NEW)}).json()
    assert "press Check again" in answer["files"][0]["reason"]
    assert releasomat_deletes.sent("delete") == []


@pytest.mark.parametrize("down", [503, TimeoutError("timed out")])
def test_without_releasomat_nothing_is_deleted_and_delete_isnt_offered(client, engine, music_dir,
                                                                       kept_out, down):  # fmt: skip
    kept_out.answers["files"] = down
    releasomat.forget_files()
    assert (
        client.post("/api/releasomat/delete", json={"ids": ids_of(engine, NEW)}).status_code == 409
    )
    assert (music_dir / AREA / NEW).exists()
    html = client.get("/releasomat").text
    assert 'name="one"' not in html and "area-actions" not in html


# --- Adopt (step 5) -------------------------------------------------------------------------


@pytest.fixture
def adoptable(kept_out, engine, settings, music_dir):
    """An import folder, and area files older than 2 minutes (read again by the area check)."""
    import os

    settings.import_dir.mkdir()
    old = __import__("time").time() - 3600
    for path in (music_dir / AREA).rglob("*.*"):
        os.utime(path, (old, old))
    area.sync(engine, settings)
    return kept_out


def adopt_now(client, engine, *paths, expect=202):
    from app.jobs import adopt_job

    answer = client.post("/api/releasomat/adopt", json={"ids": ids_of(engine, *paths)})
    assert answer.status_code == expect, answer.text
    adopt_job.wait(10)
    return adopt_job.progress


def test_adopt_tells_releasomat_first_then_moves_the_file_into_the_inbox(
    client, engine, settings, music_dir, adoptable
):
    source = music_dir / AREA / NEW
    seen_before_moving = []

    def releasomat_adopts(body):  # the file must still be in the area when Releasomat is asked
        seen_before_moving.append(source.exists())
        return {"integration_api": 1, "files": [
            {"asked": f["path"], "ok": True, "changed": True, "id": f.get("id"),
             "path": f["path"], "status": "adopted"} for f in body["files"]]}  # fmt: skip

    adoptable.answers["adopt"] = releasomat_adopts
    progress = adopt_now(client, engine, NEW)
    assert (progress.written, progress.failed) == (1, 0)
    assert seen_before_moving == [True]
    assert adoptable.sent("adopt")[0]["files"] == [
        {"path": NEW, "size": (FIXTURES / "untagged.mp3").stat().st_size, "id": 2}
    ]
    target = settings.import_dir / "Releasomat" / NEW
    assert target.read_bytes() == (FIXTURES / "untagged.mp3").read_bytes()
    assert not source.exists() and not source.parent.exists()  # the empty folder went too
    assert NEW not in {f["path"] for f in rows(client)["files"]}

    inbox = client.get("/inbox").text
    assert "From Releasomat" in inbox and "in Beatport Top 100" in inbox
    [adopted] = client.get("/api/releasomat/adoptions").json()
    assert (adopted["where"], adopted["releasomat_id"]) == ("inbox", 2)
    assert adopted["playlists"] == ["Beatport Top 100"]
    assert "In the Inbox" in client.get("/releasomat?show=adopted").text


def test_releasomat_not_answering_moves_nothing(client, engine, settings, music_dir, adoptable):
    adoptable.answers["adopt"] = TimeoutError("timed out")
    progress = adopt_now(client, engine, NEW, SAME)
    assert progress.written == 0 and "didn't answer" in progress.errors[0]
    assert "Nothing was adopted" in progress.errors[0]
    assert (music_dir / AREA / NEW).exists() and (music_dir / AREA / SAME).exists()
    assert not list(settings.import_dir.rglob("*.*"))
    assert client.get("/api/releasomat/adoptions").json() == []


def test_a_file_releasomat_refuses_stays(client, engine, settings, music_dir, adoptable):
    adoptable.answers["adopt"] = lambda body: {"integration_api": 1, "files": [
        {"asked": f["path"], "ok": f["path"] != SAME, "id": f.get("id"),
         "reason": None if f["path"] != SAME else "The file at this path has another size"}
        for f in body["files"]]}  # fmt: skip
    progress = adopt_now(client, engine, NEW, SAME)
    assert (progress.written, progress.failed) == (1, 1)
    assert progress.errors == [f"{SAME}: The file at this path has another size"]
    assert (music_dir / AREA / SAME).exists()
    assert (settings.import_dir / "Releasomat" / NEW).exists()


@pytest.mark.parametrize("problem", ["recent", "taken", "changed", "unreadable"])
def test_files_that_cant_be_adopted_are_refused_before_releasomat_is_asked(
    client, engine, settings, music_dir, adoptable, problem
):
    import os

    path, file = (BROKEN if problem == "unreadable" else NEW), music_dir / AREA / NEW
    if problem == "recent":  # maybe still being copied
        os.utime(file, None)
        area.sync(engine, settings)
    elif problem == "taken":
        (settings.import_dir / "Releasomat" / "B").mkdir(parents=True)
        (settings.import_dir / "Releasomat" / NEW).write_bytes(b"someone else's")
    elif problem == "changed":
        with open(file, "ab") as f:
            f.write(b"more")
    progress = adopt_now(client, engine, path)
    assert progress.written == 0 and progress.failed == 1
    reason = progress.errors[0]
    assert {"recent": "still new", "taken": "already in the inbox", "changed": "press Check again",
            "unreadable": "can't be read"}[problem] in reason  # fmt: skip
    assert adoptable.sent("adopt") == []
    if problem == "taken":
        assert (settings.import_dir / "Releasomat" / NEW).read_bytes() == b"someone else's"


def test_a_failed_move_leaves_the_original_and_tells_releasomat(
    client, engine, settings, music_dir, adoptable, monkeypatch
):
    from app import adopt as adopt_module
    from app.writer import WriteError

    def broken_copy(source, target):
        raise WriteError("the copy differs from the original; nothing was moved")

    monkeypatch.setattr(adopt_module, "move_file", broken_copy)
    progress = adopt_now(client, engine, NEW)
    assert progress.failed == 1 and "the move failed" in progress.errors[0]
    assert (music_dir / AREA / NEW).exists()
    assert adoptable.sent("returned") == [{"why": "move_failed", "files": [
        {"path": NEW, "size": (FIXTURES / "untagged.mp3").stat().st_size, "id": 2}]}]  # fmt: skip
    [record] = client.get("/api/releasomat/adoptions").json()
    assert record["where"] == "returned"
    with Session(engine) as session:
        assert session.exec(select(page_models.ReleasomatAdoption)).one().notice == ""  # taken


def test_a_returned_notice_waits_when_releasomat_is_gone_in_that_second(
    client, engine, settings, music_dir, adoptable, monkeypatch
):
    from app import adopt as adopt_module

    def full_disk(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(adopt_module, "move_file", full_disk)
    adoptable.answers["returned"] = 503
    adopt_now(client, engine, NEW)
    with Session(engine) as session:
        record = session.exec(select(page_models.ReleasomatAdoption)).one()
    assert (record.state, record.notice) == ("returned", "returned")
    assert "error 503" in record.notice_error and record.notice_since


def test_if_only_removing_the_original_fails_the_inbox_copy_goes(
    client, engine, settings, music_dir, adoptable, monkeypatch
):
    """The file is never in both places."""
    from pathlib import Path

    real_unlink = Path.unlink
    source = (music_dir / AREA / NEW).resolve()

    def unlink(path, *args, **kwargs):
        if Path(path).resolve() == source:
            raise PermissionError("Permission denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    progress = adopt_now(client, engine, NEW)
    assert progress.failed == 1 and (music_dir / AREA / NEW).exists()
    assert not (settings.import_dir / "Releasomat" / NEW).exists()
    assert adoptable.sent("returned")[0]["why"] == "move_failed"


def test_without_an_import_folder_adopt_isnt_offered(client, engine, kept_out):
    html = client.get("/releasomat").text
    assert "map <strong>/import</strong>" in html and 'formaction="/releasomat/adopt"' not in html
    answer = client.post("/api/releasomat/adopt", json={"ids": ids_of(engine, NEW)})
    assert answer.status_code == 409 and "map /import" in answer.json()["detail"]


def test_never_beside_another_job(client, engine, adoptable):
    from app import jobs

    with jobs._library_lock:  # a scan or write is running
        adopt_now(client, engine, NEW, expect=409)
    assert adoptable.sent("adopt") == []


def test_where_an_adopted_file_is_now(client, engine, settings, music_dir, adoptable):
    """Inbox → library (import) → Inbox again (undo) → gone (removed by hand)."""
    from app.changes import WriteProgress
    from app.importer import import_tracks
    from app.inbox import scan_inbox
    from app.scanner import ScanProgress
    from app.undo import undo_changeset

    adopt_now(client, engine, BETTER)  # tagged: ready to import
    where = lambda: client.get("/api/releasomat/adoptions").json()[0]["where"]  # noqa: E731
    assert where() == "inbox"
    with Session(engine) as session:
        inbox_id = session.exec(select(page_models.InboxTrack.id)).one()
    imported = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, [inbox_id], imported)
    assert imported.written == 1 and where() == "library"
    undone = WriteProgress(action="undo")
    undo_changeset(engine, settings.music_dir, imported.changeset_id, undone,
                   import_dir=settings.import_dir, settings=settings)  # fmt: skip
    assert where() == "inbox"
    (settings.import_dir / "Releasomat" / BETTER).unlink()
    scan_inbox(engine, settings.import_dir, ScanProgress())
    assert where() == "gone"


# --- Notices (step 6) -----------------------------------------------------------------------


@pytest.fixture
def adopted(client, engine, adoptable, monkeypatch):
    """NEW adopted into the inbox; notices are sent right away, not in a thread (tests)."""
    from app import adopt as adopt_module

    monkeypatch.setattr(adopt_module, "send_notices_soon", adopt_module.send_notices)
    assert adopt_now(client, engine, NEW).written == 1
    with Session(engine) as session:
        return session.exec(select(page_models.InboxTrack.id)).one()


def record(engine):
    with Session(engine) as session:
        return session.exec(select(page_models.ReleasomatAdoption)).one()


def test_throwing_an_adopted_file_away_tells_releasomat(client, engine, adopted, adoptable):
    page = client.get("/inbox").text
    assert "data-releasomat" in page and "came from Releasomat" in page
    client.post("/inbox/delete", data={"ids": [adopted]})
    assert adoptable.sent("discarded") == [{"files": [
        {"path": NEW, "size": (FIXTURES / "untagged.mp3").stat().st_size, "id": 2}]}]  # fmt: skip
    assert (record(engine).state, record(engine).notice) == ("discarded", "")
    assert "Thrown away in the Inbox" in client.get("/releasomat?show=adopted").text


def test_restoring_it_tells_releasomat_again(client, engine, settings, adopted, adoptable):
    from app import trash

    client.post("/inbox/delete", data={"ids": [adopted]})
    [entry] = trash.items(settings.import_dir)
    client.post(f"/inbox/trash/{entry.id}/restore")
    assert len(adoptable.sent("restored")) == 1
    assert (record(engine).state, record(engine).notice) == ("adopted", "")
    assert client.get("/api/releasomat/adoptions").json()[0]["where"] == "inbox"


def test_restored_before_releasomat_heard_of_it_sends_nothing(client, engine, settings, adopted,
                                                               adoptable):  # fmt: skip
    from app import trash

    adoptable.answers["discarded"] = 503  # Releasomat down: the notice waits
    client.post("/inbox/delete", data={"ids": [adopted]})
    assert record(engine).notice == "discarded" and "error 503" in record(engine).notice_error
    [entry] = trash.items(settings.import_dir)
    client.post(f"/inbox/trash/{entry.id}/restore")
    assert record(engine).notice == "" and adoptable.sent("restored") == []


def test_notices_are_kept_retried_and_reported_after_a_day(client, engine, settings, adopted,
                                                           adoptable):  # fmt: skip
    from datetime import UTC, datetime, timedelta

    from app import reminders

    adoptable.answers["discarded"] = TimeoutError("timed out")
    client.post("/inbox/delete", data={"ids": [adopted]})
    assert "Releasomat not told yet" in client.get("/releasomat?show=adopted").text
    settings = get_settings()  # with Releasomat's address (set by the fixture)
    reminders.run(settings)  # the regular check tries again: still down
    assert record(engine).notice == "discarded"
    with Session(engine) as session:
        late = session.exec(select(page_models.ReleasomatAdoption)).one()
        late.notice_since = datetime.now(UTC) - timedelta(days=2)
        session.add(late)
        session.commit()
    reminders.run(settings)
    with Session(engine) as session:
        notes = session.exec(select(page_models.Notification)).all()
    assert [n.summary for n in notes] == ["Releasomat hasn't taken 1 notice for a day"]
    assert "didn't answer" in notes[0].message
    reminders.run(settings)  # reported once while it lasts

    del adoptable.answers["discarded"]  # Releasomat is back
    reminders.run(settings)
    assert record(engine).notice == "" and record(engine).state == "discarded"
    with Session(engine) as session:
        summaries = [n.summary for n in session.exec(select(page_models.Notification))]
    assert summaries == [
        "Releasomat hasn't taken 1 notice for a day",
        "Releasomat took the waiting notices",
    ]


def test_other_inbox_files_send_nothing(client, engine, settings, adopted, adoptable):
    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / "mine.mp3")
    client.post("/api/inbox/scan")
    from app.jobs import inbox_job

    inbox_job.wait(10)
    with Session(engine) as session:
        mine = session.exec(
            select(page_models.InboxTrack).where(page_models.InboxTrack.path == "mine.mp3")
        ).one()
    assert "data-releasomat" not in client.get(f"/inbox/{mine.id}").text
    client.post("/inbox/delete", data={"ids": [mine.id]})
    assert adoptable.sent("discarded") == []


def test_a_quick_adopt_still_shows_its_result_and_logs_refusals(
    client, engine, settings, music_dir, adoptable, caplog
):
    """The job may end before the page it leads back to is built: then nothing polls, and a
    refusal used to go unseen ("the Adopt button does nothing")."""
    import logging
    import os

    from app.jobs import adopt_job

    os.utime(music_dir / AREA / NEW, None)  # a fresh download: refused for 2 minutes
    area.sync(engine, settings)
    caplog.set_level(logging.WARNING)
    [one] = ids_of(engine, NEW)
    answer = client.post("/releasomat/adopt", data={"one": one}, follow_redirects=False)
    assert answer.headers["location"] == "/releasomat?done=1"
    adopt_job.wait(10)  # done before the page is asked for
    page = client.get(answer.headers["location"]).text
    assert "Not adopted: " in page and "the file is still new" in page
    assert f"Not adopted: {NEW}: the file is still new" in caplog.text
    state = client.get("/api/releasomat/adopt").json()
    assert (state["status"], state["adopted"], state["failed"]) == ("done", 0, 1)

    adoptable.answers["files"] = TimeoutError("timed out")  # Releasomat busy with a refresh
    releasomat.forget_files()
    os.utime(music_dir / AREA / NEW, (1, 1))
    area.sync(engine, settings)
    client.post("/releasomat/adopt", data={"one": one})
    adopt_job.wait(10)
    page = client.get("/releasomat?done=1").text
    assert "Releasomat didn&#39;t answer" in page and "Nothing was adopted" in page
    assert "Adopt stopped: Releasomat didn't answer" in caplog.text

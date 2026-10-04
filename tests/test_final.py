from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app import changes, final, navidrome, preferences
from app.changes import WriteProgress, undo_changeset
from app.library import CHANGED_OUTSIDE
from app.models import ChangeSet, FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library

ALBUM = "Fixture Artist/Fixture Album"  # tagged.* there: complete (title … cover)


@pytest.fixture
def library(engine, settings):
    scan_library(engine, settings.music_dir, ScanProgress())
    return settings.music_dir


def track_id(engine, name: str) -> int:
    with Session(engine) as session:
        return session.exec(select(Track).where(Track.path == f"{ALBUM}/{name}")).one().id


def set_prefs(engine, **values):
    with Session(engine) as session:
        preferences.save(session, replace(preferences.load(session), **values))


def mark(engine, settings, tid) -> WriteProgress:
    progress = WriteProgress(action="final")
    final.mark(engine, settings, tid, progress)
    return progress


def test_complete_tracks_are_ready_others_not(engine, library):
    with Session(engine) as session:
        ready = {t.path for t in session.exec(select(Track).where(final.READY))}
    assert f"{ALBUM}/tagged.mp3" in ready
    assert "Unsorted/untagged.mp3" not in ready  # no title, artist, BPM, ...


def test_marking_without_renaming_keeps_the_name_and_locks(engine, settings, library):
    tid = track_id(engine, "tagged.mp3")
    progress = mark(engine, settings, tid)
    assert (progress.written, progress.failed) == (1, 0)
    assert (library / ALBUM / "tagged.mp3").exists()
    with Session(engine) as session:
        assert session.get(FinalTrack, tid).name_before is None
        assert session.exec(select(ChangeSet)).one().kind == "final"
        count, _ = changes.stage(session, [tid], {"bpm": "128"})  # locked: skipped
        assert count == 0 and not session.exec(select(PendingChange)).all()


def test_marking_renames_by_the_pattern_and_undo_renames_back(engine, settings, library):
    (library / ALBUM / "tagged.lrc").write_text("[00:01.00] la")
    set_prefs(engine, rename_on_final=True, filename_pattern="{artist} - {title} [{bpm} {key}]")
    tid = track_id(engine, "tagged.mp3")
    before = (library / ALBUM / "tagged.mp3").read_bytes()

    progress = mark(engine, settings, tid)
    assert (progress.written, progress.failed) == (1, 0)
    new = library / ALBUM / "Artist One - Silent Track [126 8A].mp3"
    assert new.read_bytes() == before  # renamed, not rewritten
    assert new.with_suffix(".lrc").exists()  # lyrics go along
    with Session(engine) as session:
        assert session.get(Track, tid).path == f"{ALBUM}/{new.name}"
        assert session.get(FinalTrack, tid).name_before == "tagged.mp3"
        changeset_id = session.exec(select(ChangeSet)).one().id

    undo = WriteProgress(action="undo")
    undo_changeset(engine, library, changeset_id, undo, settings=settings)
    assert (undo.written, undo.failed) == (1, 0)
    assert (library / ALBUM / "tagged.mp3").read_bytes() == before
    assert (library / ALBUM / "tagged.lrc").exists()
    with Session(engine) as session:
        assert session.get(FinalTrack, tid) is None
        assert session.get(Track, tid).path == f"{ALBUM}/tagged.mp3"


def test_renaming_never_overwrites(engine, settings, library):
    set_prefs(engine, rename_on_final=True, filename_pattern="{title}")
    (library / ALBUM / "Silent Track.mp3").write_bytes(b"someone else")
    progress = mark(engine, settings, track_id(engine, "tagged.mp3"))
    assert progress.failed == 1 and "already exists" in progress.errors[0]
    assert (library / ALBUM / "Silent Track.mp3").read_bytes() == b"someone else"
    with Session(engine) as session:
        assert not session.exec(select(FinalTrack)).all()  # not marked either


def test_tracks_with_pending_changes_or_missing_tags_cant_be_marked(engine, settings, library):
    tid = track_id(engine, "tagged.flac")
    with Session(engine) as session:
        changes.stage(session, [tid], {"bpm": "130"})
    with pytest.raises(final.FinalError, match="pending changes"):
        mark(engine, settings, tid)
    with Session(engine) as session:
        untagged = session.exec(select(Track).where(Track.path.endswith("untagged.mp3"))).one()
    with pytest.raises(final.FinalError, match="isn't complete"):
        mark(engine, settings, untagged.id)


def test_unmarking_can_go_back_to_the_old_name(engine, settings, library):
    set_prefs(engine, rename_on_final=True, filename_pattern="{title}")
    tid = track_id(engine, "tagged.mp3")
    mark(engine, settings, tid)
    assert (library / ALBUM / "Silent Track.mp3").exists()

    progress = WriteProgress(action="unfinal")
    final.unmark(engine, settings, tid, "tagged.mp3", progress)
    assert (progress.written, progress.failed) == (1, 0)
    assert (library / ALBUM / "tagged.mp3").exists()
    with Session(engine) as session:
        assert session.get(FinalTrack, tid) is None
        count, _ = changes.stage(session, [tid], {"bpm": "128"})  # editable again
        assert count == 1


def test_a_typed_name_keeps_the_extension_and_is_made_safe(engine, settings, library):
    tid = track_id(engine, "tagged.flac")
    mark(engine, settings, tid)
    final.unmark(engine, settings, tid, "My: Edit?", WriteProgress(action="unfinal"))
    assert (library / ALBUM / "My - Edit.flac").exists()


def test_changes_by_other_programs_are_flagged(engine, settings, library):
    import os

    tid = track_id(engine, "tagged.ogg")
    mark(engine, settings, tid)
    path = library / ALBUM / "tagged.ogg"
    later = path.stat().st_mtime + 60
    os.utime(path, (later, later))  # another tag editor wrote to the file
    scan_library(engine, library, ScanProgress())
    with Session(engine) as session:
        changed = session.exec(select(Track.id).where(CHANGED_OUTSIDE)).all()
        assert changed == [tid]
        assert session.get(FinalTrack, tid)  # the mark stays


def test_renaming_waits_until_navidrome_has_the_current_tags(monkeypatch, settings):
    calls = []
    now = datetime.now(UTC)
    states = iter([(True, now - timedelta(hours=1)), (True, now - timedelta(hours=1)),
                   (False, now + timedelta(seconds=5))])  # fmt: skip
    monkeypatch.setattr(navidrome, "configured", lambda s: True)
    monkeypatch.setattr(
        navidrome, "scan_status", lambda s: (navidrome.Result(True, "OK"), *next(states))
    )
    monkeypatch.setattr(
        navidrome, "start_scan", lambda s: calls.append("scan") or navidrome.Result(True, "")
    )
    result = navidrome.scanned_since(settings, now.timestamp(), sleep=lambda _: None)
    assert result.ok
    assert calls == []  # a scan was already running: Tagwerk only waited for it


def test_renaming_is_refused_while_navidrome_cant_confirm(monkeypatch, engine, settings, library):
    set_prefs(engine, rename_on_final=True, filename_pattern="{title}")
    monkeypatch.setattr(
        navidrome,
        "scanned_since",
        lambda s, t: navidrome.Result(False, "Navidrome is still scanning"),
    )
    progress = mark(engine, settings, track_id(engine, "tagged.mp3"))
    assert progress.failed == 1 and "still scanning" in progress.errors[0]
    assert (library / ALBUM / "tagged.mp3").exists()


# --- Pages -----------------------------------------------------------------------------------


def test_final_check_page_and_track_page(client, engine, settings):
    from app.jobs import scan_job, write_job

    client.post("/api/scan")
    scan_job.wait(30)
    page = client.get("/final").text
    assert "Mark as final" in page and "Silent Track" in page

    tid = track_id(engine, "tagged.aiff")
    client.post(f"/final/{tid}")
    write_job.wait(30)
    track_page = client.get(f"/tracks/{tid}").text
    assert "✓ Final" in track_page and "Remove final mark" in track_page
    assert client.get(f"/tracks/{tid}/edit", follow_redirects=False).status_code == 303  # locked
    assert "locked" in client.get(f"/tracks/{tid}/edit").text
    assert [t["track_id"] for t in client.get("/api/final").json()] == [tid]
    listed = client.get("/api/tracks", params={"flag": "final"}).json()["tracks"]
    assert [t["id"] for t in listed] == [tid]
    assert "Final" in client.get("/tracks?flag=final").text  # the filter chip

    client.post(f"/tracks/{tid}/unfinal", data={"name_choice": "keep"})
    write_job.wait(30)
    assert client.get("/api/final").json() == []

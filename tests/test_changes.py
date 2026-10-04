import json
import os

from mutagen.flac import FLAC
from sqlmodel import Session, select

from app import changes
from app.changes import WriteProgress
from app.models import ChangeEntry, ChangeSet, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file

ALBUM = "Fixture Artist/Fixture Album"


def scan(engine, music_dir):
    scan_library(engine, music_dir, ScanProgress())


def track_ids(engine, *names):
    with Session(engine) as session:
        rows = session.exec(select(Track)).all()
        return [t.id for t in rows if t.path.rsplit("/", 1)[-1] in names]


def apply(engine, music_dir) -> WriteProgress:
    progress = WriteProgress()
    changes.apply_pending(engine, music_dir, progress)
    return progress


def test_stage_validates_everything_first(engine, music_dir):
    scan(engine, music_dir)
    ids = track_ids(engine, "tagged.mp3")
    with Session(engine) as session:
        count, errors = changes.stage(session, ids, {"title": "Fine", "bpm": "fast"})
        assert count == 0 and "bpm" in errors
        assert changes.pending_count(session) == 0  # nothing saved when any value is wrong


def test_stage_skips_unchanged_values_and_replaces_older_edits(engine, music_dir):
    scan(engine, music_dir)
    ids = track_ids(engine, "tagged.mp3")
    with Session(engine) as session:
        count, _ = changes.stage(session, ids, {"title": "Silent Track", "bpm": "130"})
        assert count == 1  # title is unchanged, only BPM is pending
        changes.stage(session, ids, {"bpm": "131"})
        rows = session.exec(select(PendingChange)).all()
        assert [(r.field, r.old_value, r.new_value) for r in rows] == [("bpm", "126", "131")]
        changes.stage(session, ids, {"bpm": "126"})  # back to the current value
        assert changes.pending_count(session) == 0


def test_staging_does_not_touch_files(engine, music_dir):
    scan(engine, music_dir)
    before = (music_dir / ALBUM / "tagged.flac").read_bytes()
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "tagged.flac"), {"title": "Not yet"})
    assert (music_dir / ALBUM / "tagged.flac").read_bytes() == before


def test_apply_writes_records_history_and_clears_pending(engine, music_dir):
    scan(engine, music_dir)
    ids = track_ids(engine, "tagged.mp3", "tagged.flac", "tagged.m4a")
    with Session(engine) as session:
        changes.stage(session, ids, {"label": "Batch Label", "bpm": "127"})
    progress = apply(engine, music_dir)
    assert (progress.written, progress.failed) == (3, 0)
    for name in ("tagged.mp3", "tagged.flac", "tagged.m4a"):
        info = read_file(music_dir / ALBUM / name)
        assert (info.label, info.bpm) == ("Batch Label", 127.0)
    with Session(engine) as session:
        assert changes.pending_count(session) == 0
        changeset = session.exec(select(ChangeSet)).one()
        assert (changeset.tracks, changeset.written, changeset.fields) == (3, 3, "BPM, Label")
        track = session.exec(select(Track).where(Track.path == f"{ALBUM}/tagged.flac")).one()
        assert track.label == "Batch Label"  # database updated right away, no rescan needed
        entry = session.exec(select(ChangeEntry).where(ChangeEntry.track_id == track.id)).one()
        assert json.loads(entry.changes)["label"] == ["Fixture Records", "Batch Label"]
        assert entry.error is None


def test_files_changed_since_the_scan_are_not_written(engine, music_dir):
    scan(engine, music_dir)
    path = music_dir / ALBUM / "tagged.flac"
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "tagged.flac"), {"title": "Mine"})
    audio = FLAC(path)
    audio["title"] = "Edited elsewhere"
    audio.save()
    os.utime(path, (1, 1))
    progress = apply(engine, music_dir)
    assert (progress.written, progress.failed) == (0, 1)
    assert "changed since the last scan" in progress.errors[0]
    assert read_file(path).title == "Edited elsewhere"
    with Session(engine) as session:
        assert changes.pending_count(session) == 1  # kept for another try


def test_undo_restores_files_and_database(engine, music_dir):
    scan(engine, music_dir)
    ids = track_ids(engine, "tagged.mp3", "tagged.opus")
    with Session(engine) as session:
        changes.stage(session, ids, {"title": "Changed", "key": "8B"})
    apply(engine, music_dir)
    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id

    progress = WriteProgress(action="undo")
    changes.undo_changeset(engine, music_dir, changeset_id, progress)
    assert (progress.written, progress.failed) == (2, 0)
    for name in ("tagged.mp3", "tagged.opus"):
        info = read_file(music_dir / ALBUM / name)
        assert (info.title, info.key) == ("Silent Track", "Am")
    with Session(engine) as session:
        assert session.get(ChangeSet, changeset_id).undone_at is not None
        track = session.exec(select(Track).where(Track.path == f"{ALBUM}/tagged.mp3")).one()
        assert track.title == "Silent Track"


def test_undo_skips_files_edited_after_the_change(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "tagged.flac"), {"title": "Tagwerk edit"})
    apply(engine, music_dir)
    path = music_dir / ALBUM / "tagged.flac"
    audio = FLAC(path)
    audio["title"] = "Newer edit elsewhere"
    audio.save()
    os.utime(path, (2, 2))
    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id
    progress = WriteProgress(action="undo")
    changes.undo_changeset(engine, music_dir, changeset_id, progress)
    assert progress.failed == 1 and "changed after this change was applied" in progress.errors[0]
    assert read_file(path).title == "Newer edit elsewhere"  # newer edit kept


def test_pending_list_is_grouped_by_track_in_form_order(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "tagged.mp3"), {"key": "C", "title": "T"})
        items = changes.pending(session)
    assert len(items) == 1
    assert [c.field for c in items[0].changes] == ["title", "key"]


def test_discard(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "tagged.mp3", "tagged.flac"), {"title": "X"})
        first = session.exec(select(PendingChange)).first()
        changes.discard(session, first.id)
        assert changes.pending_count(session) == 1
        changes.discard(session)
        assert changes.pending_count(session) == 0


def test_only_one_job_at_a_time(settings, engine, music_dir):
    from app import jobs

    scan(engine, music_dir)
    assert jobs._library_lock.acquire(blocking=False)  # as if another job were running
    try:
        assert jobs.write_job.apply(settings) is False
        assert jobs.scan_job.start(settings) is False
    finally:
        jobs._library_lock.release()
    assert jobs.write_job.apply(settings)  # free again afterwards
    jobs.write_job.wait(30)
    assert jobs.write_job.status == "done"

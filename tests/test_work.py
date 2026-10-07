"""Tagwerk's work (app/work.py) and where changed values came from (sources)."""

import json
import re
import shutil

from sqlmodel import Session, select

from app import changes
from app.changes import WriteProgress, undo_changeset
from app.importer import import_tracks
from app.inbox import save_values, scan_inbox
from app.library import TrackFilter, find_tracks
from app.models import ChangeEntry, InboxTrack, PendingChange
from app.scanner import ScanProgress
from app.work import home_line, work_stats
from tests.conftest import FIXTURES
from tests.test_changes import apply, scan, track_ids
from tests.test_library import filter_from_url


def stage_some(engine, music_dir) -> None:
    """Title filled in (you), BPM corrected (audio), key removed (you)."""
    scan(engine, music_dir)
    with Session(engine) as session:
        changes.stage(session, track_ids(engine, "untagged.mp3"), {"title": "Now Named"})
        changes.stage(session, track_ids(engine, "tagged.mp3"), {"bpm": "128"}, "audio")
        changes.stage(session, track_ids(engine, "tagged.flac"), {"key": ""})


def test_sources_go_from_pending_changes_into_the_history(engine, music_dir):
    stage_some(engine, music_dir)
    with Session(engine) as session:
        # Saving the edit form again with the same value keeps where it came from.
        changes.stage(session, track_ids(engine, "tagged.mp3"), {"bpm": "128"})
        assert session.exec(select(PendingChange.source)).all().count("audio") == 1
    apply(engine, music_dir)
    with Session(engine) as session:
        recorded = {e.path.rsplit("/", 1)[-1]: json.loads(e.sources) for e in session.exec(
            select(ChangeEntry)
        )}  # fmt: skip
    assert recorded == {
        "untagged.mp3": {"title": "you"},
        "tagged.mp3": {"bpm": "audio"},
        "tagged.flac": {"key": "you"},
    }


def test_a_new_value_takes_the_new_source(engine, music_dir):
    scan(engine, music_dir)
    ids = track_ids(engine, "tagged.mp3")
    with Session(engine) as session:
        changes.stage(session, ids, {"bpm": "128"}, "audio")
        changes.stage(session, ids, {"bpm": "127"})  # the owner typed another value
        assert session.exec(select(PendingChange.source)).one() == "you"


def test_work_counts_what_was_filled_corrected_and_removed(engine, music_dir):
    stage_some(engine, music_dir)
    apply(engine, music_dir)
    with Session(engine) as session:
        work = work_stats(session)
        assert work.values == 3 and work.tags_tracks == 3
        assert {(f.label, f.filled, f.corrected, f.removed) for f in work.fields} == {
            ("Title", 1, 0, 0),
            ("BPM", 0, 1, 0),
            ("Key", 0, 0, 1),
        }
        assert {(s.label, s.count) for s in work.sources} == {("You", 2), ("From the audio", 1)}
        # Set-ready: both tagged files were before; the one without key isn't any more.
        ready = work.ready_library
        assert (ready.tracks, ready.before, ready.now) == (3, 2, 1)
        assert work.ready_imported is None
        assert sum(m.count for m in work.activity) == 3
        assert home_line(session) == (3, 3)
        # Every number links to a list with exactly those tracks.
        for url, expected in ((work.tags_url, work.tags_tracks), (ready.url, ready.tracks)):
            assert find_tracks(session, filter_from_url(url)).total == expected, url


def test_older_changes_count_as_source_unknown(engine, music_dir):
    stage_some(engine, music_dir)
    apply(engine, music_dir)
    with Session(engine) as session:
        for entry in session.exec(select(ChangeEntry)):
            entry.sources = None  # applied before v0.11
            session.add(entry)
        session.commit()
        work = work_stats(session)
        assert work.sources == [] and work.unknown_source == 3


def test_undone_changes_dont_count(engine, music_dir):
    stage_some(engine, music_dir)
    progress = apply(engine, music_dir)
    undo_changeset(engine, music_dir, progress.changeset_id, WriteProgress(action="undo"))
    with Session(engine) as session:
        work = work_stats(session)
        assert work.since is None and work.values == 0
        assert find_tracks(session, TrackFilter(flag="tagwerk_tags")).total == 0
        assert home_line(session) is None


def test_imports_record_where_values_came_from(engine, settings):
    root = settings.import_dir
    root.mkdir()
    name = "Fisher - Losing It (Extended Mix).mp3"
    shutil.copy(FIXTURES / "untagged.mp3", root / name)
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        track = session.exec(select(InboxTrack)).one()
        save_values(session, track, {"genre": "Liquid"})
        track_id = track.id
    progress = WriteProgress(action="import")
    import_tracks(engine, root, settings.music_dir, [track_id], progress)
    assert progress.written == 1
    with Session(engine) as session:
        entry = session.exec(select(ChangeEntry)).one()
        sources = json.loads(entry.sources)
        assert sources["genre"] == "you"
        assert sources["artist"] == sources["title"] == "filename"
        work = work_stats(session)
        assert work.imported == 1 and work.ready_imported.tracks == 1
        assert work.ready_library is None
        listed = find_tracks(session, filter_from_url(work.imported_url)).total
        assert listed == work.imported


def test_statistics_and_home_show_the_work(client, engine, music_dir):
    stage_some(engine, music_dir)
    apply(engine, music_dir)
    page = client.get("/stats").text
    assert "Tagwerk's work" in page and "Filled in" in page and "From the audio" in page
    assert "3 tag values to 3 tracks" in client.get("/").text
    assert client.get("/api/stats/work").json()["values"] == 3
    history = client.get("/changes/history").text
    detail = re.search(r'href="(/changes/history/\d+)"', history).group(1)
    assert "From the audio" in client.get(detail).text


def test_fix_ids_names_its_source(engine, music_dir):
    from app import ids

    scan(engine, music_dir)
    with Session(engine) as session:
        assert ids.stage_fixes(session, track_ids(engine, "discogs-ids.flac"))
        sources = set(session.exec(select(PendingChange.source)).all())
    assert sources == {"fix-ids"}

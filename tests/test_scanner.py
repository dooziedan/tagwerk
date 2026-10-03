import os
import shutil

from mutagen.flac import FLAC
from sqlmodel import Session, select

from app.models import Track
from app.scanner import ScanProgress, scan_library
from app.stats import library_stats
from tests.conftest import FIXTURES


def scan(engine, music_dir) -> ScanProgress:
    progress = ScanProgress()
    scan_library(engine, music_dir, progress)
    return progress


def tracks(engine) -> dict[str, Track]:
    with Session(engine) as session:
        return {t.path: t for t in session.exec(select(Track))}


def test_first_scan_adds_every_audio_file(engine, music_dir):
    (music_dir / "Unsorted" / "cover.jpg").write_bytes(b"not audio")
    progress = scan(engine, music_dir)
    assert (progress.total, progress.added, progress.errors) == (8, 8, 0)
    stored = tracks(engine)
    assert "Fixture Artist/Fixture Album/tagged.m4a" in stored
    assert stored["Fixture Artist/Fixture Album/tagged.flac"].title == "Silent Track"


def test_rescan_skips_unchanged_files(engine, music_dir):
    scan(engine, music_dir)
    progress = scan(engine, music_dir)
    assert (progress.unchanged, progress.added, progress.updated) == (8, 0, 0)


def test_changed_file_is_read_again(engine, music_dir):
    scan(engine, music_dir)
    path = music_dir / "Fixture Artist/Fixture Album/tagged.flac"
    audio = FLAC(path)
    audio["title"] = "New Title"
    audio.save()
    os.utime(path, (1, 1))  # make sure the modification time differs
    progress = scan(engine, music_dir)
    assert progress.updated == 1
    assert tracks(engine)["Fixture Artist/Fixture Album/tagged.flac"].title == "New Title"


def test_deleted_files_are_removed(engine, music_dir):
    scan(engine, music_dir)
    shutil.rmtree(music_dir / "Unsorted")
    progress = scan(engine, music_dir)
    assert progress.removed == 2
    assert len(tracks(engine)) == 6


def test_broken_file_is_recorded_and_scan_continues(engine, music_dir):
    (music_dir / "Unsorted" / "broken.mp3").write_bytes(b"\x00" * 100)
    progress = scan(engine, music_dir)
    assert progress.errors == 1
    assert progress.added == 9
    assert tracks(engine)["Unsorted/broken.mp3"].error


def test_hidden_folders_are_skipped(engine, music_dir):
    hidden = music_dir / ".Trash"
    hidden.mkdir()
    shutil.copy(FIXTURES / "tagged.mp3", hidden / "deleted.mp3")
    assert scan(engine, music_dir).total == 8


def test_stats_after_scan(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        stats = library_stats(session)
    assert stats.tracks == 8
    # Fixture Artist, Info Artist, and the Discogs file has no artist; untagged has none.
    assert stats.artists == 2
    assert stats.albums == 2  # Fixture Album, Info Album
    assert {bar.label: bar.count for bar in stats.formats} == {
        "WAV": 2,
        "MP3": 2,
        "FLAC": 2,
        "AIFF": 1,
        "M4A": 1,
    }
    missing = {bar.label: bar.count for bar in stats.missing}
    assert missing["Title"] == 1  # untagged.mp3
    assert missing["Cover art"] == 3  # riff-info.wav, untagged.mp3, discogs-ids.flac
    assert missing["MusicBrainz IDs"] == 3  # the same three; Discogs IDs count as missing
    assert stats.untagged == 1
    assert stats.invalid_mbids == 1
    assert stats.unreadable == 0

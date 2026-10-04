import os
import shutil

from mutagen.flac import FLAC
from sqlmodel import Session, select

from app.models import Track
from app.preferences import Preferences
from app.scanner import SCAN_VERSION, ScanProgress, scan_library
from app.stats import library_stats
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"
TOTAL = 10  # audio files in the test library (see conftest.music_dir)


def scan(engine, music_dir) -> ScanProgress:
    progress = ScanProgress()
    scan_library(engine, music_dir, progress)
    return progress


def tracks(engine) -> dict[str, Track]:
    with Session(engine) as session:
        return {t.path: t for t in session.exec(select(Track))}


def test_first_scan_adds_every_audio_file(engine, music_dir):
    (music_dir / "Unsorted" / "cover.jpg").write_bytes(b"not audio")
    (music_dir / "Unsorted" / "._tagged.mp3").write_bytes(b"macOS resource fork")
    progress = scan(engine, music_dir)
    assert (progress.total, progress.added, progress.errors) == (TOTAL, TOTAL, 0)
    stored = tracks(engine)
    assert stored[f"{ALBUM}/tagged.opus"].bpm == 126.0
    assert stored[f"{ALBUM}/tagged.flac"].scan_version == SCAN_VERSION


def test_rescan_skips_unchanged_files(engine, music_dir):
    scan(engine, music_dir)
    progress = scan(engine, music_dir)
    assert (progress.unchanged, progress.added, progress.updated) == (TOTAL, 0, 0)


def test_changed_file_is_read_again(engine, music_dir):
    scan(engine, music_dir)
    path = music_dir / ALBUM / "tagged.flac"
    audio = FLAC(path)
    audio["title"] = "New Title"
    audio.save()
    os.utime(path, (1, 1))  # make sure the modification time differs
    progress = scan(engine, music_dir)
    assert progress.updated == 1
    assert tracks(engine)[f"{ALBUM}/tagged.flac"].title == "New Title"


def test_rows_from_older_versions_are_read_again(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.path == f"{ALBUM}/tagged.mp3")).one()
        track.scan_version, track.bpm = 1, None  # as if scanned by v0.2
        session.commit()
    progress = scan(engine, music_dir)
    assert progress.updated == 1
    assert tracks(engine)[f"{ALBUM}/tagged.mp3"].bpm == 126.0


def test_lrc_files_are_detected_without_rereading(engine, music_dir):
    scan(engine, music_dir)
    # "Song.lrc" belongs to every "Song.*" in the same folder; use a uniquely named track.
    (music_dir / "Info Artist/Info Album/riff-info.lrc").write_text("[00:00.00] La")
    progress = scan(engine, music_dir)
    assert (progress.updated, progress.unchanged) == (1, TOTAL - 1)
    assert tracks(engine)["Info Artist/Info Album/riff-info.wav"].has_lrc is True
    assert tracks(engine)[f"{ALBUM}/tagged.mp3"].has_lrc is False


def test_deleted_files_are_removed(engine, music_dir):
    scan(engine, music_dir)
    shutil.rmtree(music_dir / "Unsorted")
    progress = scan(engine, music_dir)
    assert progress.removed == 2
    assert len(tracks(engine)) == TOTAL - 2


def test_broken_file_is_recorded_and_scan_continues(engine, music_dir):
    (music_dir / "Unsorted" / "broken.mp3").write_bytes(b"\x00" * 100)
    progress = scan(engine, music_dir)
    assert progress.errors == 1
    assert progress.added == TOTAL + 1
    assert tracks(engine)["Unsorted/broken.mp3"].error
    # Files that failed are retried on every scan, even if they didn't change...
    progress = scan(engine, music_dir)
    assert (progress.updated, progress.errors, progress.unchanged) == (1, 1, TOTAL)
    # ...and once fixed, they're read normally.
    shutil.copy(FIXTURES / "tagged.mp3", music_dir / "Unsorted" / "broken.mp3")
    os.utime(music_dir / "Unsorted" / "broken.mp3", (1, 1))
    progress = scan(engine, music_dir)
    assert (progress.updated, progress.errors) == (1, 0)
    assert tracks(engine)["Unsorted/broken.mp3"].error is None


def test_hidden_folders_are_skipped(engine, music_dir):
    hidden = music_dir / ".Trash"
    hidden.mkdir()
    shutil.copy(FIXTURES / "tagged.mp3", hidden / "deleted.mp3")
    assert scan(engine, music_dir).total == TOTAL


def stats_for(engine, **prefs):
    with Session(engine) as session:
        return library_stats(session, Preferences(**prefs))


def test_shared_stats(engine, music_dir):
    scan(engine, music_dir)
    stats = stats_for(engine)
    assert stats.tracks == TOTAL
    # Fixture Artist, Info Artist; the Discogs and untagged files have no artist.
    assert stats.artists == 2
    assert stats.albums == 2  # Fixture Album, Info Album
    assert {bar.label: bar.count for bar in stats.formats} == {
        "WAV": 2, "MP3": 2, "FLAC": 2, "AIFF": 1, "M4A": 1, "OGG": 1, "OPUS": 1,
    }  # fmt: skip
    assert {bar.label: bar.count for bar in stats.genres} == {"Electronic": 7}
    assert stats.untagged == 1
    assert stats.invalid_mbids == 1
    assert stats.unreadable == 0


def test_collector_stats(engine, music_dir):
    scan(engine, music_dir)
    stats = stats_for(engine, mode="collector")
    missing = {bar.label: bar.count for bar in stats.missing}
    assert "BPM" not in missing
    assert "MusicBrainz IDs" not in missing  # opt-in
    assert missing["Title"] == 1  # untagged.mp3
    assert missing["Cover art"] == 3  # riff-info.wav, untagged.mp3, discogs-ids.flac
    assert missing["Lyrics"] == 3
    assert [(bar.label, bar.count) for bar in stats.decades] == [("1990s", 1), ("2020s", 7)]
    assert stats.unknown_year == 2
    assert stats.with_lyrics == 7
    assert stats.bpm == []


def test_dj_stats(engine, music_dir):
    scan(engine, music_dir)
    stats = stats_for(engine, mode="dj", key_notation="musical")
    missing = {bar.label: bar.count for bar in stats.missing}
    assert missing["BPM"] == 3
    assert missing["Key"] == 3
    assert missing["Comment"] == 2  # riff-info.wav has an INFO comment
    assert [(bar.label, bar.count) for bar in stats.bpm] == [("125–129", 7)]
    am = next(cell for cell in stats.keys if cell.camelot == "8A")
    assert (am.label, am.count, am.intensity) == ("Am", 7, 100)
    assert len(stats.keys) == 24
    assert stats.with_bpm_and_key == 7
    assert stats.lossless == 5  # FLAC x2, WAV x2, AIFF
    assert stats.low_bitrate == 5  # all lossy fixtures are tiny 32 kbps files
    assert stats.decades == []


def test_musicbrainz_check_is_opt_in(engine, music_dir):
    scan(engine, music_dir)
    missing = {bar.label for bar in stats_for(engine, show_musicbrainz=True).missing}
    assert "MusicBrainz IDs" in missing


def test_empty_bpm_ranges_are_merged(engine, music_dir):
    for name, bpm in (("house", "124"), ("dnb", "174")):
        path = music_dir / "Unsorted" / f"{name}.flac"
        shutil.copy(FIXTURES / "tagged.flac", path)
        audio = FLAC(path)
        audio["bpm"] = bpm
        audio.save()
    (music_dir / ALBUM / "tagged.mp3").unlink()  # keep the test about these two clusters
    for name in (
        "tagged.flac",
        "tagged.wav",
        "tagged.aiff",
        "tagged.m4a",
        "tagged.ogg",
        "tagged.opus",
    ):
        (music_dir / ALBUM / name).unlink()
    scan(engine, music_dir)
    bars = [(bar.label, bar.count) for bar in stats_for(engine, mode="dj").bpm]
    assert bars == [("120–124", 1), ("125–169", 0), ("170–174", 1)]

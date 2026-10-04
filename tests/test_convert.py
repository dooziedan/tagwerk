import shutil
import subprocess
from dataclasses import replace

import pytest
from sqlmodel import Session, select

from app import convert, final, preferences, tagcopy
from app.changes import WriteProgress, undo_changeset
from app.models import ChangeSet, FinalTrack, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

ALBUM = "Fixture Artist/Fixture Album"
TAGS = ("title", "artist", "album", "albumartist", "date", "genre", "bpm", "key", "comment",
        "label", "catalognumber", "mb_trackid", "mb_albumid", "has_cover")  # fmt: skip


@pytest.fixture
def library(engine, settings):
    settings.originals_dir.mkdir()
    with Session(engine) as session:  # predictable target folders: one per artist
        preferences.save(session, replace(preferences.load(session), folder_layout="artist"))
    scan_library(engine, settings.music_dir, ScanProgress())
    return settings.music_dir


def tracks(engine, *names):
    with Session(engine) as session:
        rows = session.exec(select(Track)).all()
        return [t for t in rows if t.path.rsplit("/", 1)[-1] in names]


def run(engine, settings, *names) -> WriteProgress:
    progress = WriteProgress(action="convert")
    convert.convert(engine, settings, [t.id for t in tracks(engine, *names)], progress)
    return progress


def test_only_lossless_files_are_converted(engine, settings, library):
    picked = tracks(engine, "tagged.flac", "tagged.mp3", "tagged.aiff", "tagged.m4a", "tagged.ogg")
    with Session(engine) as session:
        plans = {p.track.format: p for p in convert.plan(session, settings, picked)}
    assert plans["flac"].skip is None and plans["flac"].target == "Artist One/tagged.aiff"
    assert "lossy (MP3)" in plans["mp3"].skip
    assert "lossy (OGG)" in plans["ogg"].skip
    assert "lossy (AAC)" in plans["m4a"].skip
    assert plans["aiff"].skip == "already AIFF"


def test_converting_keeps_every_tag_and_parks_the_original(engine, settings, library):
    source = library / ALBUM / "tagged.flac"
    before_bytes, before = source.read_bytes(), read_file(source)
    [track] = tracks(engine, "tagged.flac")

    progress = run(engine, settings, "tagged.flac")
    assert (progress.written, progress.failed) == (1, 0), progress.errors

    aiff = library / "Artist One" / "tagged.aiff"
    after = read_file(aiff)
    assert after.format == "aiff"
    for name in TAGS:
        assert getattr(after, name) == getattr(before, name), name
    assert after.sample_rate == before.sample_rate
    assert not source.exists()
    assert (settings.originals_dir / ALBUM / "tagged.flac").read_bytes() == before_bytes
    with Session(engine) as session:
        row = session.get(Track, track.id)  # the same track, now the AIFF
        assert (row.path, row.format) == ("Artist One/tagged.aiff", "aiff")
        changeset_id = session.exec(select(ChangeSet)).one().id

    undo = WriteProgress(action="undo")
    undo_changeset(engine, library, changeset_id, undo, settings=settings)
    assert (undo.written, undo.failed) == (1, 0), undo.errors
    assert source.read_bytes() == before_bytes
    assert not aiff.exists()
    assert not (settings.originals_dir / ALBUM / "tagged.flac").exists()
    with Session(engine) as session:
        assert session.get(Track, track.id).path == f"{ALBUM}/tagged.flac"


def test_extra_fields_are_carried_over(engine, settings, library):
    from mutagen.flac import FLAC

    source = library / ALBUM / "tagged.flac"
    audio = FLAC(source)
    audio["isrc"] = "GBXXX2600001"
    audio["my_own_field"] = "kept"
    audio.save()
    scan_library(engine, library, ScanProgress())
    run(engine, settings, "tagged.flac")
    from mutagen.aiff import AIFF

    tags = AIFF(library / "Artist One" / "tagged.aiff").tags
    assert str(tags["TSRC"]) == "GBXXX2600001"
    assert str(tags["TXXX:MY_OWN_FIELD"]) == "kept"


def test_wav_with_lyrics_file_and_riff_info(engine, settings, library):
    (library / ALBUM / "tagged.lrc").write_text("[00:01.00] la")
    progress = run(engine, settings, "tagged.wav", "riff-info.wav")
    assert (progress.written, progress.failed) == (2, 0), progress.errors
    assert (library / "Artist One" / "tagged.lrc").exists()  # the lyrics follow the track
    assert read_file(library / "Info Artist" / "riff-info.aiff").title == "Info Title"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def pcm(path) -> bytes:
    """The decoded samples, to compare audio bit for bit."""
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s32le", "-"]
    return subprocess.run(command, capture_output=True, check=True).stdout


def test_24_bit_audio_stays_24_bit_and_bit_exact(engine, settings, library):
    source = library / ALBUM / "hires.wav"
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=d=0.5:r=96000", "-ac", "2", "-c:a", "pcm_s24le", source)
    before = pcm(source)
    scan_library(engine, library, ScanProgress())
    progress = run(engine, settings, "hires.wav")
    assert (progress.written, progress.failed) == (1, 0), progress.errors
    aiff = next(library.rglob("hires.aiff"))
    info = read_file(aiff)
    assert (info.bits_per_sample, info.sample_rate) == (24, 96000)
    assert pcm(aiff) == before  # not a single sample changed


def test_alac_is_lossless_and_converted(engine, settings, library):
    alac = library / ALBUM / "alac.m4a"
    ffmpeg("-i", library / ALBUM / "tagged.flac", "-c:a", "alac", "-vn", alac)
    scan_library(engine, library, ScanProgress())
    progress = run(engine, settings, "alac.m4a")
    assert (progress.written, progress.failed) == (1, 0), progress.errors
    assert read_file(library / "Artist One" / "alac.aiff").title == "Silent Track"


def test_compressed_audio_is_skipped(engine, settings, library):
    adpcm = library / ALBUM / "adpcm.wav"
    ffmpeg("-f", "lavfi", "-i", "anullsrc=d=0.5", "-c:a", "adpcm_ima_wav", adpcm)
    scan_library(engine, library, ScanProgress())
    with Session(engine) as session:
        plans = convert.plan(session, settings, tracks(engine, "adpcm.wav", "tagged.m4a"))
    reasons = {p.track.path.rsplit("/", 1)[-1]: p.skip for p in plans}
    assert "lossy (ADPCM_IMA_WAV)" in reasons["adpcm.wav"]
    assert "lossy (AAC)" in reasons["tagged.m4a"]


def test_a_final_track_stays_final(engine, settings, library):
    [track] = tracks(engine, "tagged.flac")
    final.mark(engine, settings, track.id, WriteProgress(action="final"))
    run(engine, settings, "tagged.flac")
    with Session(engine) as session:
        mark = session.get(FinalTrack, track.id)
        assert mark and mark.mtime == session.get(Track, track.id).mtime  # not "changed outside"


def test_nothing_changes_when_the_tags_dont_match(monkeypatch, engine, settings, library):
    monkeypatch.setattr(tagcopy, "id3_frames", lambda source, riff=None: [])  # tags lost
    progress = run(engine, settings, "tagged.flac")
    assert progress.failed == 1 and "tags differ" in progress.errors[0]
    assert (library / ALBUM / "tagged.flac").exists()
    assert not (library / "Artist One").exists()
    assert not any(settings.originals_dir.rglob("*.flac"))


def test_converting_needs_the_originals_folder(engine, settings):
    assert "isn't set up" in convert.available(settings)


def test_review_page_and_convert(client, engine, settings):
    from app.jobs import scan_job, write_job

    settings.originals_dir.mkdir()
    client.post("/api/scan")
    scan_job.wait(30)
    ids = [t.id for t in tracks(engine, "tagged.flac", "tagged.mp3")]
    page = client.get("/convert", params={"ids": ids}).text
    assert "Convert 1 track to AIFF" in page and "Skipped: lossy (MP3)" in page
    client.post("/convert", data={"ids": [str(i) for i in ids]})
    write_job.wait(60)
    assert "Converted 1 track to AIFF" in client.get("/convert", params={"ids": ids}).text
    assert any(settings.music_dir.rglob("tagged.aiff"))

import shutil

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX
from sqlmodel import Session, func, select

from app.fields import field_detail, field_overview
from app.models import RawTag, Track
from app.rawtags import BINARY, used_as
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"


def scan(engine, music_dir):
    scan_library(engine, music_dir, ScanProgress())


def overview(engine):
    with Session(engine) as session:
        return {(f.system, f.name): f for f in field_overview(session)}


@pytest.mark.parametrize(
    ("system", "name", "expected"),
    [
        ("id3", "TBPM", "BPM"),
        ("id3", "TKEY", "Key"),
        ("id3", "COMM::eng", "Comment"),
        ("id3", "COMM:iTunNORM:eng", None),  # hidden player data, ignored by the reader
        ("id3", "TXXX:CATALOGNUMBER", "Catalog number"),
        ("id3", "TXXX:fBPM", None),
        ("id3", "GEOB:Key", None),
        ("vorbis", "BPM", "BPM"),  # Vorbis names are case-insensitive
        ("vorbis", "initial_key", "Key"),
        ("mp4", "----:com.apple.iTunes:LABEL", "Label"),
        ("mp4", "\xa9too", None),
        ("riff-info", "ICMT", "Comment"),
    ],
)
def test_used_as(system, name, expected):
    assert used_as(system, name) == expected


def test_raw_fields_include_unknown_and_binary_fields(tmp_path):
    path = tmp_path / "t.mp3"
    shutil.copy(FIXTURES / "tagged.mp3", path)
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc="fBPM", text="125.98"))
    tags.save(path)
    raw = {(f.system, f.name): f.value for f in read_file(path).raw}
    assert raw[("id3", "TXXX:fBPM")] == "125.98"
    assert raw[("id3", "TBPM")] == "126"
    assert raw[("id3", "APIC:Cover")] == BINARY


def test_mp4_single_value_fields(tmp_path):
    """M4A flags like cpil (compilation) are single values, not lists; this once broke reading."""
    from mutagen.mp4 import MP4

    path = tmp_path / "t.m4a"
    shutil.copy(FIXTURES / "tagged.m4a", path)
    audio = MP4(path)
    audio["cpil"] = True
    audio["pgap"] = False
    audio.save()
    info = read_file(path)
    assert info.title == "Silent Track"  # normal tags still read
    raw = {f.name: f.value for f in info.raw}
    assert (raw["cpil"], raw["pgap"]) == ("True", "False")


def test_people_frames_are_readable(tmp_path):
    from mutagen.id3 import TIPL

    path = tmp_path / "t.mp3"
    shutil.copy(FIXTURES / "tagged.mp3", path)
    tags = ID3(path)
    tags.add(TIPL(encoding=3, people=[["arranger", ""], ["mix", "DJ Someone"]]))
    tags.save(path)
    raw = {f.name: f.value for f in read_file(path).raw}
    assert raw["TIPL"] == "arranger; mix: DJ Someone"


def test_long_values_are_shortened(tmp_path):
    path = tmp_path / "t.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    audio = FLAC(path)
    audio["lyrics"] = "la " * 200
    audio.save()
    lyrics = next(f.value for f in read_file(path).raw if f.name == "lyrics")
    assert len(lyrics) == 120 and lyrics.endswith("…")


def test_scan_stores_raw_fields_and_replaces_them_on_change(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        assert session.exec(select(func.count(RawTag.id))).one() > 100
    path = music_dir / ALBUM / "tagged.flac"
    audio = FLAC(path)
    audio["bpm"] = "0"
    audio.save()
    scan(engine, music_dir)
    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.path == f"{ALBUM}/tagged.flac")).one()
        values = session.exec(
            select(RawTag.value).where(RawTag.track_id == track.id, RawTag.name == "bpm")
        ).all()
    assert values == ["0"]  # old value replaced, not duplicated


def test_deleting_a_file_removes_its_raw_fields(engine, music_dir):
    scan(engine, music_dir)
    shutil.rmtree(music_dir / "Unsorted")
    scan(engine, music_dir)
    with Session(engine) as session:
        orphans = session.exec(
            select(func.count(RawTag.id)).where(RawTag.track_id.not_in(select(Track.id)))
        ).one()
    assert orphans == 0


def test_overview_counts_zero_values_and_samples(engine, music_dir):
    path = music_dir / ALBUM / "tagged.flac"
    audio = FLAC(path)
    audio["bpm"] = "0"  # like MusicBrainz Picard writes for an unknown BPM
    audio.save()
    scan(engine, music_dir)
    fields = overview(engine)

    bpm = fields[("vorbis", "bpm")]  # FLAC, OGG, Opus
    assert (bpm.files, bpm.zero, bpm.used_as) == (3, 1, "BPM")
    assert bpm.samples[0] == ("126", 2)

    tbpm = fields[("id3", "TBPM")]  # MP3, WAV, AIFF
    assert (tbpm.files, tbpm.zero) == (3, 0)

    assert fields[("riff-info", "ISFT")].used_as is None  # encoder name, ignored
    assert fields[("id3", "APIC:Cover")].samples == [(BINARY, 3)]


def test_field_detail(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        detail = field_detail(session, "id3", "TBPM")
        missing = field_detail(session, "id3", "TXXX:doesnotexist")
    assert detail.values == [("126", 3)]
    assert [path for path, _ in detail.examples] == [
        f"{ALBUM}/tagged.aiff",
        f"{ALBUM}/tagged.mp3",
        f"{ALBUM}/tagged.wav",
    ]
    assert missing is None


def test_fields_pages_and_api(client):
    from app.jobs import scan_job

    assert "No tag fields yet" in client.get("/fields").text
    client.post("/api/scan")
    scan_job.wait(timeout=30)

    page = client.get("/fields").text
    assert "TBPM" in page and "initialkey" in page
    assert "ICMT" in client.get("/fields?system=riff-info").text
    assert "TBPM" not in client.get("/fields?show=ignored").text
    assert "No fields match" in client.get("/fields?q=nothinglikethis").text

    detail = client.get("/fields/detail", params={"system": "id3", "name": "COMM::eng"})
    assert detail.status_code == 200 and "Whatsapp Unreleased" in detail.text
    assert client.get("/fields/detail", params={"system": "id3", "name": "nope"}).status_code == 404

    api = client.get("/api/fields").json()
    assert any(f["name"] == "TBPM" and f["used_as"] == "BPM" for f in api)

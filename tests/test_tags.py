import shutil

import pytest
from mutagen import MutagenError

from app.tags import UnsupportedFileError, read_file
from tests.conftest import FIXTURES

EXPECTED = {
    "title": "Silent Track",
    "artist": "Artist One; Artist Two",
    "album": "Fixture Album",
    "albumartist": "Fixture Artist",
    "tracknumber": 3,
    "tracktotal": 12,
    "discnumber": 1,
    "disctotal": 2,
    "date": "2021-05-14",
    "year": 2021,
    "genre": "Electronic",
    "mb_trackid": "11111111-1111-4111-8111-111111111111",
    "mb_albumid": "22222222-2222-4222-8222-222222222222",
    "mb_artistid": "33333333-3333-4333-8333-333333333333",
    "mb_albumartistid": "44444444-4444-4444-8444-444444444444",
    "mbid_invalid": False,
    "has_cover": True,
}


@pytest.mark.parametrize(
    ("name", "fmt", "tag_format"),
    [
        ("tagged.mp3", "mp3", "id3"),
        ("tagged.flac", "flac", "vorbis"),
        ("tagged.wav", "wav", "id3"),
        ("tagged.aiff", "aiff", "id3"),
        ("tagged.m4a", "m4a", "mp4"),
    ],
)
def test_all_formats_read_the_same_tags(name, fmt, tag_format):
    info = read_file(FIXTURES / name)
    assert info.format == fmt
    assert info.tag_format == tag_format
    assert {key: getattr(info, key) for key in EXPECTED} == EXPECTED
    assert info.duration == pytest.approx(0.5, abs=0.2)
    assert info.sample_rate == 8000


def test_wav_falls_back_to_riff_info():
    info = read_file(FIXTURES / "riff-info.wav")
    assert info.tag_format == "riff-info"
    assert (info.title, info.artist, info.album) == ("Info Title", "Info Artist", "Info Album")
    assert (info.year, info.tracknumber) == (1999, 7)


def test_untagged_file():
    info = read_file(FIXTURES / "untagged.mp3")
    assert info.tag_format is None
    assert info.title is None
    assert info.has_cover is False


def test_non_musicbrainz_ids_are_flagged():
    info = read_file(FIXTURES / "discogs-ids.flac")
    assert info.mb_albumid == "25124086"
    assert info.mbid_invalid is True


def test_aif_extension(tmp_path):
    path = tmp_path / "track.AIF"
    shutil.copy(FIXTURES / "tagged.aiff", path)
    assert read_file(path).format == "aiff"


def test_broken_file_raises(tmp_path):
    path = tmp_path / "broken.flac"
    path.write_bytes(b"this is not audio")
    with pytest.raises((MutagenError, UnsupportedFileError)):
        read_file(path)


def test_unsupported_extension(tmp_path):
    path = tmp_path / "cover.jpg"
    path.write_bytes(b"")
    with pytest.raises(UnsupportedFileError):
        read_file(path)

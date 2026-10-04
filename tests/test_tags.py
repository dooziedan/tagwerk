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
    "has_lyrics": True,
    "bpm": 126.0,
    "key": "Am",
    "key_camelot": "8A",
    "comment": "Whatsapp Unreleased",  # the hidden iTunNORM comment is skipped
    "label": "Fixture Records",
    "catalognumber": "FIX001",
    "replaygain_track_gain": -6.2,
}


@pytest.mark.parametrize(
    ("name", "fmt", "tag_format"),
    [
        ("tagged.mp3", "mp3", "id3"),
        ("tagged.flac", "flac", "vorbis"),
        ("tagged.wav", "wav", "id3"),
        ("tagged.aiff", "aiff", "id3"),
        ("tagged.m4a", "m4a", "mp4"),
        ("tagged.ogg", "ogg", "vorbis"),
        ("tagged.opus", "opus", "vorbis"),
    ],
)
def test_all_formats_read_the_same_tags(name, fmt, tag_format):
    info = read_file(FIXTURES / name)
    assert info.format == fmt
    assert info.tag_format == tag_format
    assert {key: getattr(info, key) for key in EXPECTED} == EXPECTED
    assert info.duration == pytest.approx(0.5, abs=0.2)


def test_wav_falls_back_to_riff_info():
    info = read_file(FIXTURES / "riff-info.wav")
    assert info.tag_format == "riff-info"
    assert (info.title, info.artist, info.album) == ("Info Title", "Info Artist", "Info Album")
    assert (info.year, info.tracknumber) == (1999, 7)
    assert info.comment == "Info Comment"


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("128", 128.0), ("127.50", 127.5), ("127,5", 127.5), ("0", None), ("fast", None)],
)
def test_bpm_values(tmp_path, raw, expected):
    from mutagen.flac import FLAC

    path = tmp_path / "bpm.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    audio = FLAC(path)
    audio["bpm"] = raw
    audio.save()
    assert read_file(path).bpm == expected


@pytest.mark.parametrize("field", ["initialkey", "initial_key", "key"])
def test_vorbis_key_spellings(tmp_path, field):
    from mutagen.flac import FLAC

    path = tmp_path / "key.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    audio = FLAC(path)
    del audio["initialkey"]
    audio[field] = "F#m"
    audio.save()
    assert read_file(path).key_camelot == "11A"

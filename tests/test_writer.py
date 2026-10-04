import shutil

import mutagen
import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX

from app import writer
from app.rawtags import BINARY
from app.tags import read_file
from tests.conftest import FIXTURES

FORMATS = ["mp3", "flac", "wav", "aiff", "m4a", "ogg", "opus"]

CHANGES = {
    "title": "New Title",
    "artist": "Artist X; Artist Y",
    "album": "New Album",
    "albumartist": "New Album Artist",
    "track": "5/9",
    "disc": "2/2",
    "date": "2024-01-02",
    "genre": "House; Techno",
    "bpm": "128",
    "key": "F#m",
    "comment": "Edited by Tagwerk",
    "label": "New Label",
    "catalognumber": "NEW002",
}


def copy(tmp_path, fmt):
    path = tmp_path / f"t.{fmt}"
    shutil.copy(FIXTURES / f"tagged.{fmt}", path)
    return path


def raw(path):
    return {(f.system, f.name): f.value for f in read_file(path).raw}


@pytest.mark.parametrize("fmt", FORMATS)
def test_every_field_round_trips_in_every_format(tmp_path, fmt):
    path = copy(tmp_path, fmt)
    writer.write(path, CHANGES)
    info = read_file(path)
    assert info.title == "New Title"
    assert info.artist == "Artist X; Artist Y"
    assert (info.album, info.albumartist) == ("New Album", "New Album Artist")
    assert (info.tracknumber, info.tracktotal, info.discnumber, info.disctotal) == (5, 9, 2, 2)
    assert (info.date, info.year) == ("2024-01-02", 2024)
    assert info.genre == "House; Techno"
    assert info.bpm == 128.0
    assert (info.key, info.key_camelot) == ("F#m", "11A")
    assert info.comment == "Edited by Tagwerk"
    assert (info.label, info.catalognumber) == ("New Label", "NEW002")


@pytest.mark.parametrize("fmt", FORMATS)
def test_unrelated_fields_stay_untouched(tmp_path, fmt):
    path = copy(tmp_path, fmt)
    before = raw(path)
    writer.write(path, {"title": "Only The Title"})
    after = raw(path)
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    assert changed and all("nam" in k[1] or k[1] in ("TIT2", "title") for k in changed), changed
    assert read_file(path).has_cover  # cover art untouched


@pytest.mark.parametrize("fmt", FORMATS)
def test_undo_restores_the_exact_previous_values(tmp_path, fmt):
    path = copy(tmp_path, fmt)
    before = raw(path)
    snapshot = writer.write(path, CHANGES)
    writer.undo(path, snapshot)
    assert raw(path) == before


@pytest.mark.parametrize("fmt", FORMATS)
def test_clearing_fields(tmp_path, fmt):
    path = copy(tmp_path, fmt)
    writer.write(path, {"comment": None, "bpm": None, "key": None})
    info = read_file(path)
    assert (info.comment, info.bpm, info.key) == (None, None, None)
    assert info.title == "Silent Track"


def test_undo_restores_a_bpm_of_zero(tmp_path):
    path = copy(tmp_path, "flac")
    audio = FLAC(path)
    audio["bpm"] = "0"
    audio.save()
    snapshot = writer.write(path, {"bpm": "126"})
    assert read_file(path).bpm == 126.0
    writer.undo(path, snapshot)
    assert raw(path)[("vorbis", "bpm")] == "0"


def test_unknown_fields_survive_writes(tmp_path):
    path = copy(tmp_path, "mp3")
    tags = ID3(path)
    tags.add(TXXX(encoding=3, desc="fBPM", text="125.98"))
    tags.save(path)
    writer.write(path, {"bpm": "126", "title": "X"})
    assert raw(path)[("id3", "TXXX:fBPM")] == "125.98"


def test_hidden_comments_are_kept(tmp_path):
    path = copy(tmp_path, "mp3")  # has COMM::eng and the hidden COMM:iTunNORM:eng
    writer.write(path, {"comment": "New"})
    r = raw(path)
    assert r[("id3", "COMM::eng")] == "New"
    assert r[("id3", "COMM:iTunNORM:eng")] == "00000A 00000B"


def test_values_stay_in_the_field_the_file_already_uses(tmp_path):
    path = copy(tmp_path, "flac")
    audio = FLAC(path)
    del audio["label"]
    audio["organization"] = "Old Label"
    audio.save()
    writer.write(path, {"label": "New Label"})
    r = raw(path)
    assert r[("vorbis", "organization")] == "New Label"
    assert ("vorbis", "label") not in r


def test_id3_version_is_kept_and_new_tags_are_v23(tmp_path):
    path = copy(tmp_path, "mp3")
    writer.write(path, {"title": "X"})
    assert ID3(path).version == (2, 4, 0)

    untagged = tmp_path / "u.mp3"
    shutil.copy(FIXTURES / "untagged.mp3", untagged)
    snapshot = writer.write(untagged, {"title": "Fresh", "bpm": "127.6"})
    assert ID3(untagged).version == (2, 3, 0)
    assert read_file(untagged).bpm == 128.0  # TBPM is an integer by spec
    writer.undo(untagged, snapshot)
    assert mutagen.File(untagged).tags is None  # back to no tags at all


def test_wav_with_only_riff_info_gets_id3(tmp_path):
    path = tmp_path / "info.wav"
    shutil.copy(FIXTURES / "riff-info.wav", path)
    writer.write(path, {"title": "Now ID3"})
    info = read_file(path)
    assert (info.tag_format, info.title) == ("id3", "Now ID3")
    assert raw(path)[("riff-info", "INAM")] == "Info Title"  # INFO chunk left as it was


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("bpm", "127,50", "127.5"),
        ("bpm", " 128 ", "128"),
        ("key", "8A", "Am"),
        ("key", "1d", "C"),
        ("track", "3 / 12", "3/12"),
        ("artist", "A ;B; A", "A; B"),
        ("title", "  ", None),
        ("date", "2021", "2021"),
    ],
)
def test_normalize(field, value, expected):
    assert writer.normalize(field, value) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [("bpm", "fast"), ("bpm", "999"), ("key", "H#"), ("track", "three"), ("date", "21.5.2021")],
)
def test_normalize_rejects_bad_values(field, value):
    with pytest.raises(ValueError):
        writer.normalize(field, value)


def test_binary_fields_are_not_affected(tmp_path):
    path = copy(tmp_path, "mp3")
    writer.write(path, CHANGES)
    assert raw(path)[("id3", "APIC:Cover")] == BINARY


# --- Cover art ------------------------------------------------------------------------------

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x58\x00\x00\x02\x58\x08\x02\x00\x00\x00"
    + b"\x00" * 2000
)  # header of a 600x600 PNG; players don't decode it in these tests


@pytest.fixture
def images(tmp_path):
    from app.images import ImageStore

    return ImageStore(tmp_path / "images")


@pytest.mark.parametrize("fmt", FORMATS)
def test_cover_replace_and_undo(tmp_path, images, fmt):
    from app.covers import find_cover

    path = copy(tmp_path, fmt)
    old_cover = find_cover(path)
    before = raw(path)
    snapshot = writer.write(path, {"cover": images.put(PNG)}, images)
    assert find_cover(path) == (PNG, "image/png")
    assert read_file(path).title == "Silent Track"  # other tags untouched
    assert len(str(snapshot)) < 2000  # old pictures are kept in the image store, not inline

    writer.undo(path, snapshot, images)
    assert find_cover(path) == old_cover
    assert raw(path) == before


@pytest.mark.parametrize("fmt", FORMATS)
def test_cover_remove_and_undo(tmp_path, images, fmt):
    from app.covers import find_cover

    path = copy(tmp_path, fmt)
    old_cover = find_cover(path)
    snapshot = writer.write(path, {"cover": None}, images)
    assert not read_file(path).has_cover
    writer.undo(path, snapshot, images)
    assert find_cover(path) == old_cover


def test_cover_needs_an_image_store(tmp_path):
    with pytest.raises(writer.WriteError):
        writer.write(copy(tmp_path, "mp3"), {"cover": None})


def test_image_info_and_store(images):
    from app.images import ImageError, image_info

    assert image_info(PNG) == ("image/png", 600, 600)
    jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    jpeg += b"\xff\xc0\x00\x11\x08\x01\xf4\x03\x20\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    assert image_info(jpeg) == ("image/jpeg", 800, 500)
    with pytest.raises(ImageError):
        image_info(b"GIF89a....")
    image_id = images.put(PNG)
    assert images.put(PNG) == image_id and images.get(image_id) == PNG  # stored once
    assert not images.exists("../tagwerk.db")

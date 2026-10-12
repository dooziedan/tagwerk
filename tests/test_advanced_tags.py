"""Advanced tags (ADR 0039): any tag field of any file can be changed, added or removed, as a
pending change, applied with a snapshot and undone exactly."""

import json
import re
import shutil
from html.parser import HTMLParser
from urllib.parse import urlencode

import mutagen
import pytest
from mutagen._riff import RiffFile
from mutagen.id3 import ID3, PRIV
from sqlmodel import Session, select

from app import advanced, changes, rawtags, writer
from app.changes import WriteProgress
from app.images import ImageStore
from app.jobs import scan_job, write_job
from app.models import ChangeEntry, ChangeSet, FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from app.work import RAW_ROW, work_stats
from tests.conftest import FIXTURES

FORMATS = ["mp3", "flac", "wav", "aiff", "m4a", "ogg", "opus"]
ALBUM = "Fixture Artist/Fixture Album"
FORM = {"content-type": "application/x-www-form-urlencoded"}

# Per format: a text field the file has and Tagwerk ignores (the encoder), changed and removed,
# and a field of the DJ's own added under its own name.
EXISTING = {
    "mp3": "raw:id3:COMM:iTunNORM:eng",
    "wav": "raw:id3:COMM:iTunNORM:eng",
    "aiff": "raw:id3:COMM:iTunNORM:eng",
    "flac": "raw:vorbis:encoder",
    "ogg": "raw:vorbis:encoder",
    "opus": "raw:vorbis:encoder",
    "m4a": "raw:mp4:\xa9too",
}
SYSTEM = {"mp3": "id3", "wav": "id3", "aiff": "id3", "m4a": "mp4"}


def copy(tmp_path, name):
    path = tmp_path / name
    shutil.copy(FIXTURES / name, path)
    return path


def fields(path):
    """Every field of the file in full: (system, name) -> values (None: not text)."""
    return {(f.system, f.name): f.values for f in advanced.read(path).fields}


def found(path, field):
    return fields(path).get(writer.raw_parts(field), "absent")


def raw(*texts):
    return writer.raw_value(list(texts))


# --- Writing and undoing, every format ------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_change_add_and_remove_any_text_field_and_undo_exactly(tmp_path, fmt):
    path = copy(tmp_path, f"tagged.{fmt}")
    before = fields(path)
    mood = writer.new_raw_field(SYSTEM.get(fmt, "vorbis"), "MOOD")
    snapshot = writer.write(path, {EXISTING[fmt]: raw("Tagwerk test"), mood: raw("Dark")})
    assert found(path, EXISTING[fmt]) == ["Tagwerk test"]
    assert found(path, mood) == ["Dark"]
    after = fields(path)
    touched = {writer.raw_parts(EXISTING[fmt]), writer.raw_parts(mood)}
    assert {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)} == touched

    writer.undo(path, snapshot)
    assert fields(path) == before

    snapshot = writer.write(path, {EXISTING[fmt]: None})
    assert found(path, EXISTING[fmt]) == "absent"
    writer.undo(path, snapshot)
    assert fields(path) == before


@pytest.mark.parametrize("fmt", FORMATS)
def test_fields_that_are_not_text_can_be_removed_and_come_back(tmp_path, fmt):
    """Pictures in every format (and Traktor's private data in ID3), kept in the image store
    for undo, so the snapshot stays small."""
    path = copy(tmp_path, f"tagged.{fmt}")
    if SYSTEM.get(fmt) == "id3":
        audio = mutagen.File(path)
        audio.tags.add(PRIV(owner="TRAKTOR4", data=b"\x01" * 5000))
        audio.save()
    before = fields(path)
    binary = [name for (system, name), texts in before.items() if texts is None]
    assert binary  # every fixture has a cover
    images = ImageStore(tmp_path / "images")
    system = SYSTEM.get(fmt, "vorbis")
    snapshot = writer.write(path, {writer.raw_field(system, n): None for n in binary}, images)
    assert not read_file(path).has_cover
    assert all(texts is not None for texts in fields(path).values())
    assert len(json.dumps(snapshot)) < 4000  # pictures and private data are in the image store

    writer.undo(path, snapshot, images)
    assert fields(path) == before and read_file(path).has_cover


@pytest.mark.parametrize("fmt", FORMATS)
def test_text_never_goes_into_a_field_that_is_not_text(tmp_path, fmt):
    path = copy(tmp_path, f"tagged.{fmt}")
    picture = next(n for (s, n), texts in fields(path).items() if texts is None)
    field = writer.raw_field(SYSTEM.get(fmt, "vorbis"), picture)
    with pytest.raises(writer.WriteError):
        writer.write(path, {field: raw("not a picture")})


@pytest.mark.parametrize(
    ("fmt", "field"),
    [
        ("mp3", "raw:id3:TXXX:MOOD"),  # ID3v2.4: several texts in one frame
        ("flac", "raw:vorbis:mood"),  # one comment per value
        ("m4a", "raw:mp4:----:com.apple.iTunes:MOOD"),
    ],
)
def test_several_values(tmp_path, fmt, field):
    path = copy(tmp_path, f"tagged.{fmt}")
    writer.write(path, {field: raw("Dark", "Rolling")})
    assert found(path, field) == ["Dark", "Rolling"]


def test_id3v23_keeps_several_values_as_one(tmp_path):
    """ID3v2.3 has no several values per frame: mutagen joins them with "/"."""
    path = copy(tmp_path, "untagged.mp3")  # new ID3 tags are v2.3
    writer.write(path, {"raw:id3:TXXX:MOOD": raw("Dark", "Rolling")})
    assert mutagen.File(path).tags.version[:2] == (2, 3)
    assert found(path, "raw:id3:TXXX:MOOD") == ["Dark/Rolling"]


@pytest.mark.parametrize(
    ("fmt", "field"),
    [("mp3", "raw:id3:USLT::eng"), ("flac", "raw:vorbis:lyrics"), ("m4a", "raw:mp4:\xa9lyr")],
)
def test_lyrics_keep_their_line_breaks(tmp_path, fmt, field):
    path = copy(tmp_path, f"tagged.{fmt}")
    writer.write(path, {field: raw("First line\nSecond line")})
    assert found(path, field) == ["First line\nSecond line"]


def test_new_id3_frames_keep_their_kind(tmp_path):
    path = copy(tmp_path, "tagged.mp3")
    new = {"raw:id3:TSRC": raw("GBAAA0000001"), "raw:id3:WXXX:Shop": raw("https://shop"),
           "raw:id3:COMM:DJ notes:eng": raw("Big drop at 1:30")}  # fmt: skip
    writer.write(path, new)
    tags = ID3(path)
    assert tags["TSRC"].text == ["GBAAA0000001"] and tags["WXXX:Shop"].url == "https://shop"
    assert tags["COMM:DJ notes:eng"].text == ["Big drop at 1:30"]
    assert read_file(path).comment == "Whatsapp Unreleased; Big drop at 1:30"  # a comment too


def test_normal_field_wins_when_both_are_written(tmp_path):
    path = copy(tmp_path, "tagged.mp3")
    before = fields(path)
    snapshot = writer.write(path, {"bpm": "128", "raw:id3:TBPM": raw("127")})
    assert read_file(path).bpm == 128
    writer.undo(path, snapshot)
    assert fields(path) == before


# --- RIFF INFO (WAV) --------------------------------------------------------------------------


def test_riff_info_fields_change_and_undo_byte_for_byte(tmp_path):
    path = copy(tmp_path, "riff-info.wav")
    original = path.read_bytes()
    snapshot = writer.write(path, {"raw:riff-info:INAM": raw("Ä new title"),
                                   "raw:riff-info:ICMT": None,
                                   "raw:riff-info:IGNR": raw("House")})  # fmt: skip
    info = fields(path)
    assert info[("riff-info", "INAM")] == ["Ä new title"] and ("riff-info", "ICMT") not in info
    assert info[("riff-info", "IGNR")] == ["House"]
    assert read_file(path).title == "Ä new title"  # read as before: no ID3, so RIFF INFO
    assert mutagen.File(path).tags is None  # no ID3 tag was added
    assert mutagen.File(path).info.length == pytest.approx(0.5, abs=0.1)  # the audio is intact
    writer.undo(path, snapshot)
    assert path.read_bytes() == original

    everything = {writer.raw_field(s, n): None for s, n in fields(path)}
    snapshot = writer.write(path, everything)
    assert fields(path) == {}
    writer.undo(path, snapshot)
    assert path.read_bytes() == original


def test_riff_info_chunk_is_added_and_removed_again(tmp_path):
    path = copy(tmp_path, "tagged.wav")
    with path.open("r+b") as f:  # a WAV without RIFF INFO
        next(c for c in RiffFile(f).root.subchunks() if c.id == "LIST").delete()
    original = path.read_bytes()
    snapshot = writer.write(
        path, {"raw:riff-info:ISFT": raw("Tagwerk"), "raw:id3:TXXX:X": raw("1")}
    )
    assert found(path, "raw:riff-info:ISFT") == ["Tagwerk"]
    assert found(path, "raw:id3:TXXX:X") == ["1"] and read_file(path).title == "Silent Track"
    writer.undo(path, snapshot)
    assert path.read_bytes() == original


def test_riff_info_only_in_wav(tmp_path):
    path = copy(tmp_path, "tagged.aiff")
    with pytest.raises(writer.WriteError):
        writer.write(path, {"raw:riff-info:ISFT": raw("Tagwerk")})
    with pytest.raises(writer.WriteError):  # nor Vorbis fields in an ID3 file
        writer.write(path, {"raw:vorbis:mood": raw("Dark")})


# --- Names and values -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("system", "typed", "field"),
    [
        ("id3", "MOOD", "raw:id3:TXXX:MOOD"),
        ("id3", "txxx:Energy", "raw:id3:TXXX:Energy"),
        ("id3", "tsrc", "raw:id3:TSRC"),
        ("id3", "COMM:DJ notes", "raw:id3:COMM:DJ notes:eng"),
        ("id3", "COMM:Notizen:deu", "raw:id3:COMM:Notizen:deu"),
        ("id3", "WOAF", "raw:id3:WOAF"),
        ("vorbis", "MOOD", "raw:vorbis:mood"),
        ("mp4", "MOOD", "raw:mp4:----:com.apple.iTunes:MOOD"),
        ("mp4", "\xa9grp", "raw:mp4:\xa9grp"),
        ("mp4", "----:com.serato.dj:key", "raw:mp4:----:com.serato.dj:key"),
        ("riff-info", "isft", "raw:riff-info:ISFT"),
    ],
)
def test_names_typed_for_new_fields(system, typed, field):
    assert writer.new_raw_field(system, typed) == field
    assert writer.new_raw_field(system, writer.raw_parts(field)[1]) == field  # stays the same


@pytest.mark.parametrize(
    ("system", "typed"),
    [("id3", ""), ("id3", "APIC"), ("id3", "PRIV"), ("id3", "TXXX:"), ("id3", "TIT2:x"),
     ("id3", "WCOM"), ("vorbis", "a=b"), ("vorbis", "METADATA_BLOCK_PICTURE"), ("mp4", "covr"),
     ("mp4", "trkn"), ("mp4", "----:x:"), ("riff-info", "ABC"), ("ape", "MOOD")],
)  # fmt: skip
def test_names_that_cannot_hold_text(system, typed):
    with pytest.raises(ValueError):
        writer.new_raw_field(system, typed)


def test_id3v23_files_get_no_frames_it_would_drop():
    assert writer.new_raw_field("id3", "TMOO") == "raw:id3:TMOO"
    with pytest.raises(ValueError, match="ID3v2.4"):
        writer.new_raw_field("id3", "TMOO", id3v23=True)


def test_values_are_cleaned_and_checked():
    assert writer.normalize_raw("raw:id3:TXXX:X", [" a ", "", "b\r\nc"]) == ["a", "b\nc"]
    assert writer.normalize_raw("raw:id3:TXXX:X", ["", "  "]) is None  # nothing left: removed
    for field in ("raw:riff-info:INAM", "raw:id3:USLT::eng", "raw:id3:WXXX:"):
        with pytest.raises(ValueError, match="one value"):
            writer.normalize_raw(field, ["a", "b"])
    assert writer.normalize_raw("raw:id3:TDRC", ["2021-05-14"]) == ["2021-05-14"]
    with pytest.raises(ValueError, match="date"):
        writer.normalize_raw("raw:id3:TDRC", ["May 2021"])


def test_every_field_that_feeds_tagwerk_names_a_field_it_can_edit():
    """used_as() labels map to the writer's fields (Lyrics has no field of its own), so the
    normal field can always win."""
    tables = (rawtags._ID3, rawtags._VORBIS, rawtags._MP4, rawtags._RIFF)
    for label in {text for table in tables for text in table.values()} - {"Lyrics"}:
        assert label in writer._FEEDS, label
    assert writer.feeds("raw:id3:TBPM") == "bpm"
    assert writer.feeds("raw:vorbis:tempo") == "bpm"
    assert writer.feeds("raw:mp4:trkn") == "track"
    assert writer.feeds("raw:id3:APIC:Cover") == writer.COVER
    assert writer.feeds("raw:id3:TXXX:MOOD") is None


def test_every_text_field_of_every_fixture_can_be_written_back(tmp_path):
    """What the reader offers as text, the writer can write (unchanged values, same fields)."""
    for fixture in FIXTURES.glob("*.*"):
        if fixture.suffix in (".py",):
            continue
        path = copy(tmp_path, fixture.name)
        tags = advanced.read(path)
        texts = {writer.raw_field(f.system, f.name): writer.raw_value(f.values)
                 for f in tags.fields if f.values}  # fmt: skip
        before = fields(path)
        snapshot = writer.write(path, texts)
        assert fields(path) == before, fixture.name
        writer.undo(path, snapshot)
        assert fields(path) == before, fixture.name


# --- Staging ----------------------------------------------------------------------------------


def scan(engine, music_dir):
    scan_library(engine, music_dir, ScanProgress())


def track(session, name) -> Track:
    return next(t for t in session.exec(select(Track)) if t.path.endswith("/" + name))


def stage(session, music_dir, name, values):
    t = track(session, name)
    return changes.stage_raw(session, t, advanced.read(music_dir / t.path), values)


def pending(session):
    return {c.field: (c.old_value, c.new_value) for c in session.exec(select(PendingChange))}


def test_stage_raw_keeps_old_and_new_texts(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        count, errors = stage(session, music_dir, "tagged.flac", {
            "raw:vorbis:encoder": ["Tagwerk"], "raw:vorbis:mood": ["Dark", "Rolling"],
            "raw:vorbis:(FLAC picture block)": None,
        })  # fmt: skip
        assert (count, errors) == (3, {})
        assert pending(session) == {
            "raw:vorbis:encoder": ('["Lavf63.1.102"]', '["Tagwerk"]'),
            "raw:vorbis:mood": (None, '["Dark", "Rolling"]'),
            "raw:vorbis:(FLAC picture block)": ('["<binary data>"]', None),
        }
        # Back to the file's value (after cleaning): the pending change goes.
        stage(session, music_dir, "tagged.flac", {"raw:vorbis:encoder": [" Lavf63.1.102 "]})
        assert "raw:vorbis:encoder" not in pending(session)
        # A new field without a value isn't added
        stage(session, music_dir, "tagged.flac", {"raw:vorbis:mood": [""]})
        assert "raw:vorbis:mood" not in pending(session)


def test_stage_raw_checks_everything_first(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        cases = {
            "raw:vorbis:encoder": ["fine"],
            "raw:vorbis:(FLAC picture block)": ["text"],  # not text: only removable
            "raw:id3:TXXX:MOOD": ["x"],  # a FLAC has no ID3
            "raw:vorbis:MOOD": ["x"],  # not how Tagwerk names it (lower case)
        }
        count, errors = stage(session, music_dir, "tagged.flac", cases)
        assert count == 0 and set(errors) == set(cases) - {"raw:vorbis:encoder"}
        assert pending(session) == {}
        _, errors = stage(session, music_dir, "tagged.mp3", {"raw:id3:TDRC": ["May"]})
        assert "date" in errors["raw:id3:TDRC"]


def test_final_tracks_stay_locked(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        t = track(session, "tagged.mp3")
        session.add(FinalTrack(track_id=t.id, mtime=t.mtime, name_before="x"))
        session.commit()
        assert stage(session, music_dir, "tagged.mp3", {"raw:id3:TXXX:MOOD": ["x"]}) == (0, {})
        assert pending(session) == {}


def test_the_normal_field_wins(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        t = track(session, "tagged.mp3")
        edits = {"raw:id3:TBPM": ["127"], "raw:id3:APIC:Cover": None, "raw:id3:TXXX:MOOD": ["x"]}
        stage(session, music_dir, "tagged.mp3", edits)
        changes.stage(session, [t.id], {"bpm": "128"})  # the BPM above replaces TBPM's change
        changes.stage_cover(session, [t.id], None)  # and the cover the picture's
        assert set(pending(session)) == {"bpm", "cover", "raw:id3:TXXX:MOOD"}
        # While BPM is pending, a TBPM edit isn't saved
        stage(session, music_dir, "tagged.mp3", {"raw:id3:TBPM": ["127"]})
        assert "raw:id3:TBPM" not in pending(session)
        changes.stage(session, [t.id], {"bpm": "126"})  # BPM back as in the file
        assert stage(session, music_dir, "tagged.mp3", {"raw:id3:TBPM": ["127"]})[0] == 1


def test_apply_verifies_and_undo_restores(engine, music_dir):
    scan(engine, music_dir)
    path = music_dir / ALBUM / "tagged.wav"
    before = fields(path)
    with Session(engine) as session:
        edits = {"raw:id3:COMM:iTunNORM:eng": None, "raw:riff-info:ISFT": ["Tagwerk"],
                 "raw:id3:TXXX:MOOD": ["Dark"]}  # fmt: skip
        stage(session, music_dir, "tagged.wav", edits)
    progress = WriteProgress()
    changes.apply_pending(engine, music_dir, progress)
    assert (progress.written, progress.failed) == (1, 0)
    assert found(path, "raw:riff-info:ISFT") == ["Tagwerk"]
    with Session(engine) as session:
        entry = session.exec(select(ChangeEntry)).one()
        assert entry.error is None  # read back as written
        changeset_id = entry.changeset_id
        assert session.get(ChangeSet, changeset_id).fields == (
            "COMM:iTunNORM:eng (ID3), TXXX:MOOD (ID3), ISFT (RIFF INFO)"
        )
        assert set(json.loads(entry.changes)) == {
            "raw:id3:COMM:iTunNORM:eng",
            "raw:riff-info:ISFT",
            "raw:id3:TXXX:MOOD",
        }
    changes.undo_changeset(engine, music_dir, changeset_id, WriteProgress())
    assert fields(path) == before


def test_statistics_count_advanced_tags(engine, music_dir):
    scan(engine, music_dir)
    with Session(engine) as session:
        stage(session, music_dir, "tagged.mp3", {"raw:id3:TXXX:MOOD": ["Dark"]})
    changes.apply_pending(engine, music_dir, WriteProgress())
    with Session(engine) as session:
        row = next(w for w in work_stats(session).fields if w.label == RAW_ROW)
        assert (row.filled, row.corrected, row.removed) == (1, 0, 0)


# --- The edit page and the API -----------------------------------------------------------------


def scanned(client):
    client.post("/api/scan")
    scan_job.wait(30)
    return {t["path"]: t["id"] for t in client.get("/api/tracks").json()["tracks"]}


def post(client, track_id, pairs):
    """Send the edit form like a browser: every value of a field under its name."""
    url = f"/tracks/{track_id}/edit"
    return client.post(url, content=urlencode(pairs), headers=FORM, follow_redirects=False)


class FormReader(HTMLParser):
    """The edit form as a browser sends it untouched: inputs and text areas with their values,
    ticked boxes and radio buttons, the chosen option of each select."""

    def __init__(self):
        super().__init__()
        self.pairs: list[tuple[str, str]] = []
        self.textarea: list[str] | None = None  # name, text so far
        self.select: str | None = None
        self.options: list[tuple[str, bool]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        kind = a.get("type")
        if tag == "input" and "name" in a and kind != "file":
            if kind not in ("checkbox", "radio") or "checked" in a:
                self.pairs.append((a["name"], a.get("value") or ("on" if kind else "")))
        elif tag == "textarea":
            self.textarea = [a["name"], ""]
        elif tag == "select":
            self.select, self.options = a["name"], []
        elif tag == "option" and self.select:
            self.options.append((a["value"], "selected" in a))

    def handle_data(self, data):
        if self.textarea:
            self.textarea[1] += data

    def handle_endtag(self, tag):
        if tag == "textarea" and self.textarea:  # a browser drops the newline after <textarea>
            self.pairs.append((self.textarea[0], self.textarea[1].removeprefix("\n")))
            self.textarea = None
        elif tag == "select" and self.select:
            chosen = next((v for v, selected in self.options if selected), self.options[0][0])
            self.pairs.append((self.select, chosen))
            self.select = None


def form_of(page: str) -> list[tuple[str, str]]:
    reader = FormReader()
    reader.feed(page)
    return reader.pairs


def test_edit_page_shows_every_field_and_saves_changes(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.mp3"]
    page = client.get(f"/tracks/{track_id}/edit").text
    switch = re.compile(r'<input type="checkbox" role="switch" id="adv-switch"[^>]*>')
    assert "checked" not in switch.search(page).group()  # closed unless asked for
    assert (
        "checked" in switch.search(client.get(f"/tracks/{track_id}/edit?advanced=1").text).group()
    )
    assert "<code>TXXX:CATALOGNUMBER</code>" in page and ">Catalog number</span>" in page
    assert "<code>APIC:Cover</code>" in page and "&lt;binary data&gt;" in page
    assert "ID3v2.4" in page

    # Sent untouched (switched on): nothing changes.
    untouched = form_of(page) + [("advanced", "on")]
    assert post(client, track_id, untouched).status_code == 303
    assert client.get("/api/changes").json() == []

    pairs = [(k, v) for k, v in untouched if k != "raw:id3:TXXX:CATALOGNUMBER"]
    pairs += [
        ("raw:id3:TXXX:CATALOGNUMBER", "NEW001"),
        ("raw_remove", "raw:id3:COMM:iTunNORM:eng"),
        ("raw_new_system", "id3"),
        ("raw_new_name", "MOOD"),
        ("raw_new_value", "Dark"),
    ]
    saved = post(client, track_id, pairs)
    assert saved.status_code == 303, saved.text
    staged = {c["field"]: c["new_value"] for c in client.get("/api/changes").json()[0]["changes"]}
    assert staged == {
        "raw:id3:TXXX:CATALOGNUMBER": '["NEW001"]',
        "raw:id3:COMM:iTunNORM:eng": None,
        "raw:id3:TXXX:MOOD": '["Dark"]',
    }

    review = client.get("/changes").text
    assert "TXXX:MOOD (ID3)" in review and "<ins>Dark</ins>" in review
    assert "&#34;Dark&#34;" not in review  # the texts, not their JSON

    page = client.get(f"/tracks/{track_id}/edit").text
    assert "checked" in switch.search(page).group()  # opens by itself while some wait
    assert "new</span>" in page.split("<code>TXXX:MOOD</code>")[1][:100]
    assert "pending</span>" in page.split("<code>TXXX:CATALOGNUMBER</code>")[1][:100]
    client.post("/changes/apply", data={"backup": "on"})
    write_job.wait(30)
    path = music_dir / ALBUM / "tagged.mp3"
    tags = ID3(path)
    assert tags["TXXX:MOOD"].text == ["Dark"] and "COMM:iTunNORM:eng" not in tags
    assert read_file(path).catalognumber == "NEW001"
    assert "TXXX:MOOD (ID3)" in client.get("/changes/history").text


def test_switched_off_advanced_tags_are_left_alone(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.flac"]
    pairs = form_of(client.get(f"/tracks/{track_id}/edit").text)
    pairs = [(k, "Changed" if k == "raw:vorbis:encoder" else v) for k, v in pairs]
    assert ("advanced", "on") not in pairs
    post(client, track_id, pairs)
    assert client.get("/api/changes").json() == []


def test_a_wrong_field_saves_nothing(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.mp3"]
    pairs = form_of(client.get(f"/tracks/{track_id}/edit").text) + [("advanced", "on")]
    pairs = [(k, "Changed title" if k == "title" else v) for k, v in pairs]
    pairs += [("raw_new_system", "id3"), ("raw_new_name", "APIC"), ("raw_new_value", "x")]
    response = post(client, track_id, pairs)
    assert response.status_code == 422 and "can&#39;t be typed in" in response.text
    assert 'value="APIC"' in response.text  # what was typed comes back
    assert client.get("/api/changes").json() == []  # not even the title


def test_normal_field_wins_on_the_form(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.mp3"]
    pairs = form_of(client.get(f"/tracks/{track_id}/edit").text) + [("advanced", "on")]
    pairs = [(k, {"bpm": "130", "raw:id3:TBPM": "127"}.get(k, v)) for k, v in pairs]
    post(client, track_id, pairs)
    staged = {c["field"]: c["new_value"] for c in client.get("/api/changes").json()[0]["changes"]}
    assert staged == {"bpm": "130"}
    page = client.get(f"/tracks/{track_id}/edit?advanced=1").text
    assert "BPM above has a pending change" in page


def test_wav_can_add_id3_or_riff_info_fields(client, music_dir):
    ids = scanned(client)
    track_id = ids["Info Artist/Info Album/riff-info.wav"]
    page = client.get(f"/tracks/{track_id}/edit").text
    assert '<option value="riff-info"' in page and "RIFF INFO" in page
    pairs = [(k, v) for k, v in form_of(page) if not k.startswith("raw_new")]
    pairs += [("advanced", "on"), ("raw_new_system", "riff-info"), ("raw_new_name", "ICOP")]
    pairs += [("raw_new_value", "2026 Orbit Stage")]
    assert post(client, track_id, pairs).status_code == 303
    client.post("/changes/apply", data={"backup": "on"})
    write_job.wait(30)
    path = music_dir / "Info Artist/Info Album/riff-info.wav"
    assert found(path, "raw:riff-info:ICOP") == ["2026 Orbit Stage"]
    assert mutagen.File(path).tags is None  # still no ID3


def test_unreadable_file_says_so(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.ogg"]
    (music_dir / ALBUM / "tagged.ogg").unlink()
    page = client.get(f"/tracks/{track_id}/edit?advanced=1")
    assert page.status_code == 200 and "can't be read right now" in page.text


def test_track_page_links_to_advanced_tags(client):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.mp3"]
    assert f"/tracks/{track_id}/edit?advanced=1" in client.get(f"/tracks/{track_id}").text


def test_api_lists_fields_and_stages_raw_changes(client, music_dir):
    ids = scanned(client)
    track_id = ids[f"{ALBUM}/tagged.m4a"]
    listed = client.get(f"/api/tracks/{track_id}/fields").json()
    by_field = {f["field"]: f for f in listed["fields"]}
    assert listed["systems"] == ["mp4"]
    assert by_field["raw:mp4:covr"]["values"] is None
    assert by_field["raw:mp4:\xa9too"]["values"] == ["Lavf63.1.102"]
    assert by_field["raw:mp4:tmpo"]["used_as"] == "BPM"

    body = {"track_ids": [track_id], "raw": {"raw:mp4:----:com.apple.iTunes:MOOD": ["Dark"]}}
    assert client.post("/api/changes", json=body).json() == {"pending": 1}
    bad = {"track_ids": [track_id], "raw": {"raw:mp4:covr": ["text"]}}
    response = client.post("/api/changes", json=bad)
    assert response.status_code == 422 and str(track_id) in response.json()["detail"]

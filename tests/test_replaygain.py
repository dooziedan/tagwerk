"""ReplayGain: read, edited on the edit page, applied and undone in every format (ADR 0028)."""

import shutil

from mutagen.oggopus import OggOpus
from sqlmodel import Session, select

from app import changes
from app.changes import WriteProgress
from app.models import ChangeEntry, ChangeSet, Track
from app.rawtags import used_as
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"
FORMATS = ["mp3", "flac", "wav", "aiff", "m4a", "ogg", "opus"]
VALUES = {
    "replaygain_track_gain": "-7.25 dB",
    "replaygain_track_peak": "0.988525",
    "replaygain_album_gain": "-8.10 dB",
    "replaygain_album_peak": "1.012000",
}


def scanned(engine, music_dir) -> dict[str, int]:
    scan_library(engine, music_dir, ScanProgress())
    with Session(engine) as session:
        paths = {t.path: t.id for t in session.exec(select(Track))}
    return {fmt: paths[f"{ALBUM}/tagged.{fmt}"] for fmt in FORMATS}


def test_replaygain_is_applied_and_read_back_in_every_format(engine, music_dir):
    ids = scanned(engine, music_dir)
    with Session(engine) as session:
        saved, errors = changes.stage(session, list(ids.values()), VALUES)
    assert not errors
    assert saved == 4 * 7 - 2  # Opus has no peak fields: those two are skipped
    progress = WriteProgress()
    changes.apply_pending(engine, music_dir, progress)
    assert (progress.written, progress.failed) == (7, 0)
    with Session(engine) as session:
        entries = session.exec(select(ChangeEntry)).all()
        assert [e.error for e in entries] == [None] * 7  # every file reads back as written
        opus = session.get(Track, ids["opus"])
        assert opus.replaygain_track_peak is None
        assert round(opus.replaygain_album_gain, 2) == -8.1  # in steps of 1/256 dB
        flac = session.get(Track, ids["flac"])
        assert flac.replaygain_album_peak == 1.012
        changeset_id = session.exec(select(ChangeSet)).one().id

    changes.undo_changeset(engine, music_dir, changeset_id, WriteProgress(action="undo"))
    for fmt in FORMATS:
        info = read_file(music_dir / ALBUM / f"tagged.{fmt}")
        assert (info.replaygain_track_gain, info.replaygain_album_gain) == (-6.2, None), fmt


def test_opus_r128_gains_are_read(tmp_path):
    path = tmp_path / "t.opus"
    shutil.copy(FIXTURES / "tagged.opus", path)
    audio = OggOpus(path)
    audio["R128_TRACK_GAIN"] = ["-2867"]  # -11.2 dB below -23 LUFS: -6.2 dB in ReplayGain
    audio["R128_ALBUM_GAIN"] = ["256"]
    audio.save()
    info = read_file(path)
    assert round(info.replaygain_track_gain, 2) == -6.2
    assert info.replaygain_album_gain == 6.0
    assert used_as("vorbis", "R128_TRACK_GAIN") == "ReplayGain track gain"
    assert used_as("id3", "TXXX:REPLAYGAIN_ALBUM_PEAK") == "ReplayGain album peak"


def test_the_edit_page_has_a_replaygain_section(client, engine, settings):
    ids = scanned(engine, settings.music_dir)
    flac = client.get(f"/tracks/{ids['flac']}/edit").text
    assert "ReplayGain" in flac and 'value="-6.20 dB"' in flac
    assert 'name="replaygain_album_peak"' in flac
    opus = client.get(f"/tracks/{ids['opus']}/edit").text
    assert 'name="replaygain_album_gain"' in opus and 'name="replaygain_album_peak"' not in opus
    assert "no peaks" in opus

    bad = client.post(f"/tracks/{ids['flac']}/edit", data={"replaygain_track_gain": "loud"})
    assert bad.status_code == 422 and "A gain is a number of dB" in bad.text
    saved = client.post(
        f"/tracks/{ids['flac']}/edit",
        data={"replaygain_album_gain": "-8.1", "replaygain_track_gain": "-6.20 dB"},
        follow_redirects=False,
    )
    assert saved.headers["location"].endswith("saved=1")  # the track gain didn't change
    [pending] = client.get("/api/changes").json()
    assert [(c["field"], c["new_value"]) for c in pending["changes"]] == [
        ("replaygain_album_gain", "-8.10 dB")
    ]
    assert "ReplayGain album gain" in client.get("/changes").text

    many = client.get(f"/tracks/edit?ids={ids['flac']}&ids={ids['opus']}").text
    assert 'name="change_replaygain_album_peak"' in many and "peaks are skipped there" in many

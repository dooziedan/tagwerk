"""Loudness from the audio and the ReplayGain check (app/loudness.py, ADR 0029)."""

import shutil

import pytest
from sqlmodel import Session, select

from app import analysis, changes, loudness
from app.changes import WriteProgress
from app.models import FinalTrack, LibraryLoudness, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"
SUMMARY = """[Parsed_ebur128_0 @ 0x5581] Summary:

  Integrated loudness:
    I:          -7.0 LUFS
    Threshold: -17.3 LUFS

  Loudness range:
    LRA:         4.1 LU

  True peak:
    Peak:        1.0 dBFS
"""


def test_parse_the_ebur128_summary():
    assert loudness.parse(SUMMARY) == {"lufs": -7.0, "peak": round(10 ** (1 / 20), 6)}
    with pytest.raises(loudness.LoudnessError, match="silent"):
        loudness.parse(SUMMARY.replace("-7.0 LUFS", "-inf LUFS").replace("-17.3", "-inf"))
    with pytest.raises(loudness.LoudnessError, match="no loudness"):
        loudness.parse("garbage")


def test_measure_a_real_file_and_a_silent_one():
    found = loudness.measure(FIXTURES / "dnb-174-7A.ogg")
    assert -30 < found["lufs"] < -3 and 0 < found["peak"] < 2
    assert loudness.measure(FIXTURES / "tagged.flac") == {"error": "The audio is silent"}
    assert "Can't read the audio" in loudness.measure(FIXTURES / "generate.py")["error"]


def _track(**tags):
    values = {"id": 1, "path": "a.flac", "format": "flac", "replaygain_track_gain": None,
              "replaygain_track_peak": None} | tags  # fmt: skip
    return Track(**values)


ROW = LibraryLoudness(track_id=1, lufs=-7.0, peak=1.122018, version=loudness.LOUDNESS_VERSION)


@pytest.mark.parametrize(
    ("tags", "status", "difference"),
    [
        ({}, "missing", None),
        ({"replaygain_track_gain": -11.3, "replaygain_track_peak": 1.1}, "ok", -0.3),
        ({"replaygain_track_gain": -7.0, "replaygain_track_peak": 1.1}, "old", 4.0),  # RG 1
        ({"replaygain_track_gain": -2.5, "replaygain_track_peak": 1.1}, "differs", 8.5),
        ({"replaygain_track_gain": -11.0}, "no_peak", 0.0),
        ({"replaygain_track_gain": -11.0, "format": "opus"}, "ok", 0.0),  # Opus has no peak
    ],
)
def test_check_compares_the_tags_with_the_measurement(tags, status, difference):
    found = loudness.check(_track(**tags), ROW)
    assert (found.status, found.difference) == (status, difference)
    assert (found.gain, found.peak) == ("-11.00 dB", "1.122018")  # -18 LUFS - (-7 LUFS)


def library(engine, music_dir) -> dict[str, int]:
    scan_library(engine, music_dir, ScanProgress())
    with Session(engine) as session:
        paths = {t.path: t.id for t in session.exec(select(Track))}
    return {fmt: paths[f"{ALBUM}/tagged.{fmt}"] for fmt in ("mp3", "flac", "opus", "m4a")}


def measured(engine, values: dict[int, float]) -> None:
    """Stand-in measurements (the fixtures are silent), as fresh results."""
    with Session(engine) as session:
        for track_id, lufs in values.items():
            loudness.store(session, track_id, {"lufs": lufs, "peak": 0.9},
                           session.get(Track, track_id).duration)  # fmt: skip


def test_library_analysis_measures_loudness_once(engine, settings, monkeypatch):
    ids = library(engine, settings.music_dir)
    calls = []
    monkeypatch.setattr(loudness, "measure", lambda p: calls.append(p) or {"lufs": -8.0, "peak": 1})
    assert analysis.analyse_track(engine, settings, ids["flac"], library=True)
    assert len(calls) == 1
    # BPM/key and loudness are fresh now: nothing to do, unless forced.
    assert not analysis.analyse_track(engine, settings, ids["flac"], library=True)
    with Session(engine) as session:
        session.delete(
            session.get(LibraryLoudness, ids["flac"])
        )  # e.g. analysed before loudness was measured
        session.commit()
    assert analysis.analyse_track(engine, settings, ids["flac"], library=True)
    assert len(calls) == 2  # only the quick loudness pass ran again


def test_fixes_are_staged_and_applied(engine, settings):
    """The fixtures' track gain is -6.20 dB: right for -11.8 LUFS, old ReplayGain 1 for
    -7.8 LUFS, missing peaks otherwise. Final tracks are skipped; Opus gets no peak."""
    ids = library(engine, settings.music_dir)
    measured(engine, {ids["mp3"]: -11.8, ids["flac"]: -7.8, ids["opus"]: -5.0, ids["m4a"]: -6.0})
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids["m4a"], mtime=0))
        session.commit()
        found = loudness.overview(session)
        statuses = {c.track.id: c.status for c in found.checks}
        assert statuses == {
            ids["mp3"]: "no_peak", ids["flac"]: "old", ids["opus"]: "differs",
            ids["m4a"]: "differs",
        }  # fmt: skip
        assert [c.track.id for c in found.to_fix] == [ids["flac"], ids["opus"], ids["mp3"]]
        assert loudness.stage_fixes(session) == 2 + 1 + 1  # FLAC gain+peak, Opus gain, MP3 peak
        pending = {(c.track_id, c.field): c.new_value for c in session.exec(select(PendingChange))}
        assert pending == {
            (ids["flac"], "replaygain_track_gain"): "-10.20 dB",
            (ids["flac"], "replaygain_track_peak"): "0.900000",
            (ids["opus"], "replaygain_track_gain"): "-13.00 dB",
            (ids["mp3"], "replaygain_track_peak"): "0.900000",
        }
        assert {c.source for c in session.exec(select(PendingChange))} == {"audio"}
    changes.apply_pending(engine, settings.music_dir, WriteProgress())
    assert read_file(settings.music_dir / ALBUM / "tagged.flac").replaygain_track_gain == -10.2
    with Session(engine) as session:
        assert loudness.fix_count(session) == 0  # the final M4A isn't counted


def test_the_page_measures_and_fixes(client, engine, settings, monkeypatch):
    ids = library(engine, settings.music_dir)
    page = client.get("/replaygain").text
    assert "not measured yet" in page and "CDJs and XDJs don't read them" in page
    home = client.get("/").text
    assert "without measured loudness" in home  # found before anything is measured
    for url in ("/replaygain", "/convert", "/mix-names", "/genres"):  # the Tools menu
        assert f'href="{url}"' in home

    started = []
    monkeypatch.setattr(
        "app.routes.replaygain.analysis_job.start",
        lambda settings, track_ids, library, loudness_only: started.append(
            (sorted(track_ids), library and loudness_only)
        ),
    )
    client.post("/replaygain/measure")
    assert started and started[0][1] is True and ids["flac"] in started[0][0]

    measured(engine, {ids["flac"]: -7.8, ids["mp3"]: -11.8})
    page = client.get("/replaygain").text
    assert "Old ReplayGain 1 value" in page and "-10.20 dB" in page
    assert "with ReplayGain missing or not matching the audio" in client.get("/").text
    assert "Loudness" in client.get(f"/tracks/{ids['flac']}").text

    response = client.post("/replaygain/fix", data={"track": [ids["flac"]]}, follow_redirects=False)
    assert response.headers["location"] == "/changes?saved=2"
    api = client.get("/api/replaygain").json()
    assert api["counts"]["old"] == 1 and api["unmeasured"] > 0
    assert client.post("/api/replaygain/fix", json={}).json() == {"pending_changes": 1}


def test_a_replaced_file_is_measured_again(engine, settings):
    ids = library(engine, settings.music_dir)
    measured(engine, {ids["flac"]: -8.0})
    shutil.copy(FIXTURES / "dnb-174-7A.ogg", settings.music_dir / ALBUM / "tagged.flac")
    with Session(engine) as session:
        track = session.get(Track, ids["flac"])
        track.duration = 99.0  # another file under the same name
        assert not loudness.fresh(session.get(LibraryLoudness, track.id), track)


def test_the_job_can_measure_only_the_loudness(engine, settings, monkeypatch):
    """The ReplayGain page's "Measure" skips BPM and key (seconds per track)."""
    from app.jobs import AnalysisJob

    ids = library(engine, settings.music_dir)
    monkeypatch.setattr(analysis, "run_analysis", lambda path: pytest.fail("BPM/key analysed"))
    monkeypatch.setattr(loudness, "measure", lambda path: {"lufs": -9.0, "peak": 0.8})
    job = AnalysisJob()
    job.start(settings, [ids["flac"], ids["mp3"]], library=True, loudness_only=True)
    job.wait(30)
    assert (job.progress.processed, job.progress.failed) == (2, 0)
    with Session(engine) as session:
        assert session.get(LibraryLoudness, ids["mp3"]).lufs == -9.0

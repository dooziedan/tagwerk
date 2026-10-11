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


# --- The track page: ReplayGain as a suggestion in the "From the audio" box (issue #71) -----


def audio_box(client, track_id: int) -> str:
    page = client.get(f"/tracks/{track_id}").text
    return page[page.index('id="audio"') :].split("</article>")[0]


def analysed(engine, track_id: int) -> None:
    """A stored BPM/key result (the box shows its table)."""
    from app.audio_analysis import ANALYSIS_VERSION
    from tests.conftest import FAKE_ANALYSIS

    with Session(engine) as session:
        duration = session.get(Track, track_id).duration
        found = FAKE_ANALYSIS | {"version": ANALYSIS_VERSION}
        analysis.store(session, track_id, True, found, duration)


def untagged(engine) -> int:
    with Session(engine) as session:
        return session.exec(select(Track.id).where(Track.path.endswith("untagged.mp3"))).one()


@pytest.mark.parametrize(
    ("fmt", "lufs", "line", "button"),
    [
        ("opus", -11.8, "· ReplayGain -6.20 dB ✓ matches", None),  # Opus: no peak needed
        (
            "flac",
            -7.8,
            "ReplayGain -6.20 dB in the file is an old ReplayGain 1 value, about 4 "
            "dB too loud: it should be -10.20 dB (peak 0.900).",
            "Use -10.20 dB",
        ),
        (
            "flac",
            -5.0,
            "ReplayGain -6.20 dB in the file doesn't match the audio: it should be "
            "-13.00 dB (peak 0.900).",
            "Use -13.00 dB",
        ),
        ("opus", -5.0, "it should be -13.00 dB.", "Use -13.00 dB"),
        ("mp3", -11.8, "The peak is missing: the audio says 0.900.", "Add the peak"),
    ],
)
def test_the_box_says_what_is_wrong_with_the_replaygain(
    client, engine, settings, fmt, lufs, line, button
):
    track_id = library(engine, settings.music_dir)[fmt]
    measured(engine, {track_id: lufs})
    box = audio_box(client, track_id)
    assert f"<strong>{lufs:.1f} LUFS</strong>" in box and line in box
    if button:
        assert f'action="/tracks/{track_id}/replaygain"' in box and f">{button}</button>" in box
    else:
        assert "/replaygain" not in box


def test_the_box_offers_missing_replaygain(client, engine, settings):
    library(engine, settings.music_dir)
    track_id = untagged(engine)
    measured(engine, {track_id: -8.0})
    box = audio_box(client, track_id)
    assert "ReplayGain is missing: the audio says -10.00 dB (peak 0.900)." in box
    assert ">Add ReplayGain</button>" in box
    assert "BPM and key not analysed yet." in box  # measured on the ReplayGain page


def test_the_box_before_and_after_measuring(client, engine, settings):
    ids = library(engine, settings.music_dir)
    box = audio_box(client, ids["flac"])  # nothing analysed: Analyse does both
    assert "Analyse measures BPM, key and loudness." in box and "/loudness" not in box
    analysed(engine, ids["flac"])  # e.g. imported from the inbox: BPM and key came along
    box = audio_box(client, ids["flac"])
    assert "Loudness not measured yet" in box and ">Measure loudness</button>" in box
    with Session(engine) as session:
        duration = session.get(Track, ids["flac"]).duration
        loudness.store(session, ids["flac"], {"error": "The audio is silent"}, duration)
    box = audio_box(client, ids["flac"])
    assert "Couldn't measure the loudness: The audio is silent" in box
    assert "Measure loudness" not in box and "LUFS" not in box


def test_final_and_pending_tracks_get_no_button(client, engine, settings):
    ids = library(engine, settings.music_dir)
    measured(engine, {ids["flac"]: -7.8, ids["mp3"]: -7.8})
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids["flac"], mtime=0))
        session.commit()
        loudness.stage_fixes(session, [ids["mp3"]])
    box = audio_box(client, ids["flac"])
    assert "-7.8 LUFS" in box and "Final: your tags stand" in box
    assert "/replaygain" not in box and "old ReplayGain 1" not in box
    page = client.get(f"/tracks/{ids['flac']}").text
    assert 'href="#audio"' not in page  # the File card doesn't point at a fix either
    box = audio_box(client, ids["mp3"])
    assert "old ReplayGain 1 value" in box and "ReplayGain fix waits on the Changes page" in box
    assert "<button" not in box.split("old ReplayGain 1 value")[1]
    page = client.get(f"/tracks/{ids['mp3']}").text
    assert 'href="#audio">Old ReplayGain 1 value' in page  # the File card's status link


def test_the_button_stages_the_fix_for_this_track_only(client, engine, settings):
    ids = library(engine, settings.music_dir)
    measured(engine, {ids["flac"]: -7.8, ids["mp3"]: -7.8, ids["opus"]: -5.0, ids["m4a"]: -5.0})
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids["m4a"], mtime=0))
        session.commit()
    response = client.post(f"/tracks/{ids['flac']}/replaygain", follow_redirects=False)
    assert response.headers["location"] == f"/tracks/{ids['flac']}?saved=2#audio"
    with Session(engine) as session:
        check = loudness.track_check(session, session.get(Track, ids["flac"]))
        pending = {(c.track_id, c.field): c.new_value for c in session.exec(select(PendingChange))}
    assert pending == {(ids["flac"], name): value for name, value in check.values.items()}
    assert check.pending  # the box says it waits on Changes now

    assert client.post(f"/api/tracks/{ids['opus']}/replaygain/fix").json() == {
        "pending_changes": 1  # Opus: the gain, no peak
    }
    assert client.post(f"/api/tracks/{ids['m4a']}/replaygain/fix").json() == {
        "pending_changes": 0  # final
    }
    assert client.post("/api/tracks/99999/replaygain/fix").status_code == 404


def test_a_fix_whose_peak_is_already_right_counts_as_pending(client, engine, settings):
    """Only the gain becomes a pending change (the file has the peak); that's the whole fix."""
    ids = library(engine, settings.music_dir)
    measured(engine, {ids["flac"]: -7.8})
    with Session(engine) as session:
        session.get(Track, ids["flac"]).replaygain_track_peak = 0.9  # as measured
        session.commit()
    assert client.post(f"/api/tracks/{ids['flac']}/replaygain/fix").json() == {"pending_changes": 1}
    assert "ReplayGain fix waits on the Changes page" in audio_box(client, ids["flac"])
    with Session(engine) as session:
        assert loudness.overview(session).to_fix == []  # nor on the ReplayGain page


def test_measure_queues_only_this_track_for_its_loudness(client, engine, settings, monkeypatch):
    ids = library(engine, settings.music_dir)
    started = []
    monkeypatch.setattr(
        "app.routes.analysis.analysis_job.start",
        lambda settings, track_ids, **options: started.append((track_ids, options)),
    )
    response = client.post(f"/tracks/{ids['flac']}/loudness", follow_redirects=False)
    assert response.headers["location"] == f"/tracks/{ids['flac']}#audio"
    assert client.post(f"/api/tracks/{ids['mp3']}/loudness").status_code == 202
    options = {"force": True, "library": True, "loudness_only": True}
    assert started == [([ids["flac"]], options), ([ids["mp3"]], options)]
    assert client.post("/api/tracks/99999/loudness").status_code == 404


def test_the_box_keeps_bpm_and_key_while_the_loudness_is_measured(
    client, engine, settings, monkeypatch
):
    """Measuring only the loudness takes seconds: BPM and key stay, the line says so. A full
    analysis asked for meanwhile shows as one."""
    import threading

    from app.jobs import analysis_job

    ids = library(engine, settings.music_dir)
    analysed(engine, ids["flac"])
    release = threading.Event()
    monkeypatch.setattr(
        loudness, "measure", lambda path: release.wait(10) and {"lufs": -9.0, "peak": 0.8}
    )
    try:
        client.post(f"/tracks/{ids['flac']}/loudness")
        assert analysis_job.measuring_loudness(ids["flac"])
        box = audio_box(client, ids["flac"])
        assert "Measuring the loudness… about 2 seconds" in box and '<th scope="row">BPM' in box
        assert "analysis-status" in box  # polls until it's done
        analysis_job.start(settings, [ids["flac"]], force=True, library=True)
        assert not analysis_job.measuring_loudness(ids["flac"])
        assert "Measuring BPM, key and loudness" in audio_box(client, ids["flac"])
    finally:
        release.set()
        analysis_job.wait(30)
    assert "-9.0 LUFS" in audio_box(client, ids["flac"])

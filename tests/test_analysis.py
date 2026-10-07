"""Running and storing the audio analysis (app/analysis.py) and its background job.

The analysis itself is replaced by a quick stand-in (``quick_analysis`` in conftest.py);
one test runs the real thing in its own process.
"""

import shutil

import pytest
from sqlmodel import Session, select

from app import analysis
from app.analysis import run_analysis as real_run_analysis  # bound before the stand-in
from app.audio_analysis import ANALYSIS_VERSION
from app.changes import WriteProgress
from app.importer import import_tracks
from app.inbox import scan_inbox
from app.jobs import AnalysisJob, analysis_job, inbox_job
from app.models import InboxAnalysis, InboxTrack, LibraryAnalysis, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FAKE_ANALYSIS, FIXTURES

NAME = "Hoax - Big Up.ogg"


@pytest.fixture
def library_track(engine, settings) -> int:
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        return session.exec(select(Track.id).where(Track.path.endswith("tagged.flac"))).first()


@pytest.fixture
def inbox_track(engine, settings) -> int:
    settings.import_dir.mkdir()
    shutil.copy(FIXTURES / "dnb-174-7A.ogg", settings.import_dir / NAME)
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        return session.exec(select(InboxTrack.id)).one()


def stored(engine, track_id, library=False):
    with Session(engine) as session:
        return analysis.result(session, track_id, library)


# --- Storing ---------------------------------------------------------------------------


def test_analyse_and_store_a_library_track(engine, settings, library_track):
    assert analysis.analyse_track(engine, settings, library_track, library=True)
    row = stored(engine, library_track, library=True)
    assert (row.bpm, row.bpm_sure, row.key, row.key_sure) == (87.0, False, "7A", True)
    assert row.version == ANALYSIS_VERSION and row.error is None
    assert analysis.detail(row)["bpm_alternatives"] == [174.0]
    assert analysis.detail(row)["notes"] == ["All 3 tempo methods measured 87 BPM"]


def test_fresh_results_are_kept(engine, settings, library_track, monkeypatch):
    analysis.analyse_track(engine, settings, library_track, library=True)
    monkeypatch.setattr(analysis, "run_analysis", lambda path: pytest.fail("analysed again"))
    assert not analysis.analyse_track(engine, settings, library_track, library=True)


def test_analysed_again_when_forced_or_the_method_changed(engine, settings, library_track):
    analysis.analyse_track(engine, settings, library_track, library=True)
    assert analysis.analyse_track(engine, settings, library_track, library=True, force=True)
    with Session(engine) as session:
        session.get(LibraryAnalysis, library_track).version = ANALYSIS_VERSION - 1
        session.commit()
    assert analysis.analyse_track(engine, settings, library_track, library=True)


def test_writing_tags_keeps_the_result_but_a_new_length_doesnt(engine, settings, library_track):
    analysis.analyse_track(engine, settings, library_track, library=True)
    with Session(engine) as session:
        track = session.get(Track, library_track)
        row = analysis.result(session, library_track, library=True)
        track.mtime += 100  # tags written: same sound
        assert analysis.fresh(row, track)
        track.duration += 30  # another file under the same name
        assert not analysis.fresh(row, track)


def test_a_failed_analysis_is_stored_with_its_reason(engine, settings, library_track, monkeypatch):
    monkeypatch.setattr(analysis, "run_analysis", lambda path: {"error": "The audio is silent"})
    analysis.analyse_track(engine, settings, library_track, library=True)
    row = stored(engine, library_track, library=True)
    assert row.error == "The audio is silent" and row.bpm is None and row.key is None


def test_the_real_analysis_runs_in_its_own_process():
    if shutil.which("ffmpeg") is None:
        pytest.skip("needs ffmpeg")
    found = real_run_analysis(FIXTURES / "dnb-174-7A.ogg")
    assert found["key"] == "7A" and found["bpm"] == 87.0 and found["error"] is None


def test_a_crashing_analysis_becomes_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(analysis.sys, "executable", "false")  # exits at once, prints nothing
    assert real_run_analysis(tmp_path / "x.mp3") == {"error": "The analysis stopped unexpectedly"}


# --- Inbox and import ------------------------------------------------------------------


def test_the_inbox_check_analyses_new_tracks(client, engine, settings, inbox_track):
    inbox_job.start(settings)
    inbox_job.wait(30)
    analysis_job.wait(30)
    assert stored(engine, inbox_track).key == "7A"
    answer = client.get(f"/api/inbox/{inbox_track}/analysis").json()
    assert answer["status"] == "done"
    assert (answer["bpm"], answer["bpm_alternatives"], answer["key"]) == (87.0, [174.0], "7A")


def test_import_takes_the_result_along(engine, settings, inbox_track, monkeypatch):
    analysis.analyse_track(engine, settings, inbox_track)
    with Session(engine) as session:  # give it an artist, so it can be imported
        session.get(InboxTrack, inbox_track).artist = "Hoax"
        session.commit()
    monkeypatch.setattr(analysis, "run_analysis", lambda path: pytest.fail("analysed again"))
    progress = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, [inbox_track], progress)
    assert progress.written == 1
    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.path.endswith(NAME))).one()
        row = analysis.result(session, track.id, library=True)
        assert (row.bpm, row.key) == (87.0, "7A")
        assert session.exec(select(InboxAnalysis)).all() == []  # gone with the inbox track


# --- The job ---------------------------------------------------------------------------


def test_inbox_tracks_go_first_then_in_order():
    job = AnalysisJob()
    for key in [(True, 5), (True, 3), (False, 9), (True, 1)]:
        job._queue[key] = False
    order = [job._next()[0] for _ in range(4)]
    assert order == [(False, 9), (True, 5), (True, 3), (True, 1)]
    assert job._next() is None


def test_stop_forgets_waiting_tracks():
    job = AnalysisJob()
    job._queue = {(True, 1): False, (True, 2): False}
    assert job.stop() == 2 and job._next() is None


def test_analyse_library_tracks_through_the_api(client, engine, library_track):
    assert client.get(f"/api/tracks/{library_track}/analysis").json() == {"status": "not analysed"}
    response = client.post("/api/tracks/analyse", json={"track_ids": [library_track]})
    assert response.status_code == 202
    analysis_job.wait(30)
    answer = client.get(f"/api/tracks/{library_track}/analysis").json()
    assert answer["status"] == "done" and answer["key"] == "7A" and answer["key_sure"]
    status = client.get("/api/analysis").json()
    assert (status["processed"], status["failed"], status["running"]) == (1, 0, False)
    assert client.get("/api/tracks/999999/analysis").status_code == 404


def test_fake_matches_the_real_fields():
    """The stand-in answers with the same fields as audio_analysis.Analysis."""
    from dataclasses import fields

    from app.audio_analysis import Analysis

    assert set(FAKE_ANALYSIS) == {f.name for f in fields(Analysis)}


# --- Deciding: audio + genre + hints ---------------------------------------------------


def stored_row(bpm, alternatives=(), sure=False, key="7A", key_alternatives=(), key_sure=True):
    import json
    from types import SimpleNamespace

    more = {"bpm_alternatives": list(alternatives), "key_alternatives": list(key_alternatives)}
    return SimpleNamespace(
        error=None, bpm=bpm, bpm_sure=sure, key=key, key_sure=key_sure, detail=json.dumps(more)
    )


@pytest.mark.parametrize(
    ("genre", "expected"),
    [
        ("Liquid Funk; Dubstep; Drum And Bass", "Liquid Funk"),
        ("Drum And Bass, Dubstep, Uk Garage", "Drum And Bass"),
        ("Electronic", None),  # not "electro"
        ("Electronic; Tech House", "Tech House"),
        (None, None),
    ],
)
def test_genre_tempo(genre, expected):
    found = analysis.genre_tempo(genre)
    assert (found[0] if found else None) == expected


def test_the_genre_settles_half_or_double_time():
    # The Samurai: the audio hears 87, could be 174; drum & bass is 160-185.
    found = analysis.decide(stored_row(87.0, [174.0]), "Drum and bass; Electronic", [], [])
    assert (found.bpm, found.bpm_sure) == (174.0, True)
    assert found.bpm_notes == ["Drum and bass is 160-185 BPM: 174, not 87"]


def test_a_hint_means_the_tempo_it_matches_directly():
    # On My Mind: 87.5 or 175; a store's 176 (88 x 2, rounded) means 175, not 87.5.
    found = analysis.decide(stored_row(87.5, [175.0]), None, [(176, "Beatport")], [])
    assert (found.bpm, found.bpm_sure) == (175.0, True)


def test_a_half_time_hint_agrees_with_the_genres_tempo():
    found = analysis.decide(stored_row(87.0, [174.0]), "Drum & Bass", [(87, "Deezer")], [])
    assert (found.bpm, found.bpm_sure) == (174.0, True)
    assert found.bpm_notes[-1] == "Deezer agrees (87 BPM, half or double time)"


def test_a_disagreeing_filename_makes_it_unsure_but_a_tag_doesnt():
    row = stored_row(130.0, sure=True)
    found = analysis.decide(row, "House", [(128, "The filename")], [])
    assert (found.bpm, found.bpm_sure) == (130.0, False)
    assert found.bpm_notes == ["The filename says 128 BPM, the audio doesn't"]
    assert analysis.decide(row, "House", [(128, "your tag")], []).bpm_sure


def test_a_key_hint_picks_between_what_the_audio_allows():
    # DRZ - Dance: the audio hears 2A or 5B; the filename says 5B.
    row = stored_row(None, key="2A", key_alternatives=["5B"], key_sure=False)
    found = analysis.decide(row, None, [], [("5B", "The filename")])
    assert (found.key, found.key_sure) == ("5B", True)


# --- Library: pending changes and flags ------------------------------------------------


def library_with(engine, settings, monkeypatch, **answer):
    """Analyse every library track with this answer from the audio."""
    monkeypatch.setattr(
        analysis,
        "run_analysis",
        lambda path: FAKE_ANALYSIS | {"version": ANALYSIS_VERSION} | answer,
    )
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        ids_ = list(session.exec(select(Track.id).where(Track.error.is_(None))))
    for track_id in ids_:
        analysis.analyse_track(engine, settings, track_id, library=True)
    return ids_


def pending(engine, path_end):
    from app.models import PendingChange

    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.path.endswith(path_end))).one()
        rows = session.exec(select(PendingChange).where(PendingChange.track_id == track.id))
        return {c.field: c.new_value for c in rows}


def test_sure_values_for_empty_fields_become_pending_changes(engine, settings, monkeypatch):
    library_with(engine, settings, monkeypatch)
    # untagged.mp3 has no genre: 87 or 174 stays open, the sure key is staged.
    assert pending(engine, "untagged.mp3") == {"key": "Dm"}
    # tagged.flac already has BPM 126 and key Am: nothing is staged, only flagged.
    assert pending(engine, "tagged.flac") == {}


def test_tags_that_differ_from_the_audio_are_flagged(client, engine, settings, monkeypatch):
    from app.library import TrackFilter, find_tracks

    library_with(engine, settings, monkeypatch, bpm=63.0, bpm_sure=True, bpm_alternatives=[])
    with Session(engine) as session:
        octave = find_tracks(session, TrackFilter(flag="audio_bpm_octave")).total
        key = find_tracks(session, TrackFilter(flag="audio_key_differs")).total
        missing = find_tracks(session, TrackFilter(flag="not_analysed")).total
    assert octave >= 7  # the fixtures say 126 BPM: double the 63 the audio "hears"
    assert key >= 7  # Am (8A) in the files, D minor (7A) from the audio
    assert missing == 0
    client.put("/api/settings", json=client.get("/api/settings").json() | {"mode": "dj"})
    page = client.get("/stats").text
    assert "with a BPM at probably half or double the real tempo" in page
    assert "tracks with a BPM at probably half or double time" in client.get("/").text  # Home

    with Session(engine) as session:
        track_id = session.exec(select(Track.id).where(Track.path.endswith("tagged.flac"))).one()
    page = client.get(f"/tracks/{track_id}").text
    assert "BPM 126 in the file is probably double time: the audio says 63." in page
    response = client.post(
        f"/tracks/{track_id}/audio", data={"field": "key"}, follow_redirects=False
    )
    assert response.headers["location"] == f"/tracks/{track_id}?saved=1#audio"
    assert pending(engine, "Fixture Album/tagged.flac") == {"key": "Dm"}


def test_analyse_all_matching_tracks_from_the_list(client, engine, settings):
    scan_library(engine, settings.music_dir, ScanProgress())
    page = client.get("/tracks?flag=not_analysed").text
    assert "Analyse all" in page
    client.post("/tracks/analyse?flag=not_analysed", data={"all": "true"})
    analysis_job.wait(30)
    assert "No tracks match" in client.get("/tracks?flag=not_analysed").text


# --- Inbox: suggestions ----------------------------------------------------------------


def test_inbox_suggestions_come_from_the_audio_and_the_genre(engine, settings, inbox_track):
    from app.inbox import save_values, suggestions

    analysis.analyse_track(engine, settings, inbox_track)
    with Session(engine) as session:
        track = session.get(InboxTrack, inbox_track)
        found = suggestions(session, track)
        assert (found["bpm"].value, found["bpm"].sure) == ("87", False)
        assert (found["key"].value, found["key"].sure) == ("Dm", True)
        assert found["key"].reason == "From the audio"
        save_values(session, track, {"genre": "Drum & Bass"})  # the owner sets the genre
        found = suggestions(session, track)
        assert (found["bpm"].value, found["bpm"].sure) == ("174", True)
        assert "Drum & Bass is 160-185 BPM" in found["bpm"].reason


def test_automatic_import_waits_for_the_analysis(engine, settings, inbox_track):
    from app.duplicates import LibraryIndex
    from app.importer import ready_for_auto_import

    with Session(engine) as session:
        track = session.get(InboxTrack, inbox_track)
        later = track.mtime + 3600
        library = LibraryIndex.load(session)
        args = (settings.import_dir, settings.music_dir, later, library)
        assert not ready_for_auto_import(session, track, *args)  # not analysed yet


def test_a_half_time_tag_doesnt_confirm_the_genres_tempo():
    # Big Up tagged 86: the genre says 172; the tag matches only the audio's raw reading.
    found = analysis.decide(stored_row(86.0, [172.0]), "Drum & Bass", [(86, "your tag")], [])
    assert (found.bpm, found.bpm_sure) == (172.0, True)
    assert found.bpm_notes == ["Drum & Bass is 160-185 BPM: 172, not 86"]


# --- Parallel analyses -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("setting", "cores", "limit", "memory_gb", "expected"),
    [
        (0, 12, None, 32, 12),  # no limits: every core
        (0, 12, 4, 32, 4),  # docker-compose cpus: 4
        (0, 12, None, 2, 2),  # 2 GB: two long mixes at most
        (0, 1, None, None, 1),
        (3, 12, None, 32, 3),  # ANALYSIS_WORKERS=3
    ],
)
def test_worker_count(monkeypatch, settings, setting, cores, limit, memory_gb, expected):
    monkeypatch.setattr(analysis.os, "sched_getaffinity", lambda pid: set(range(cores)))
    monkeypatch.setattr(analysis, "_cgroup_cpu_limit", lambda: limit)
    monkeypatch.setattr(analysis, "available_memory", lambda: memory_gb and memory_gb * 1024**3)
    monkeypatch.setattr(settings, "analysis_workers", setting)
    assert analysis.worker_count(settings) == expected


def test_several_tracks_are_analysed_at_once(engine, settings, monkeypatch):
    import threading
    import time

    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        track_ids = list(session.exec(select(Track.id).where(Track.error.is_(None))))
    at_once, most = [0], [0]
    lock = threading.Lock()

    def slow(path):
        with lock:
            at_once[0] += 1
            most[0] = max(most[0], at_once[0])
        time.sleep(0.2)
        with lock:
            at_once[0] -= 1
        return FAKE_ANALYSIS | {"version": ANALYSIS_VERSION}

    monkeypatch.setattr(analysis, "run_analysis", slow)
    monkeypatch.setattr(settings, "analysis_workers", 4)
    job = AnalysisJob()
    job.start(settings, track_ids, library=True)
    job.wait(30)
    assert job.workers == 4 and most[0] == 4
    assert (job.progress.processed, job.progress.total) == (len(track_ids), len(track_ids))
    with Session(engine) as session:
        assert all(analysis.result(session, i, library=True) for i in track_ids)

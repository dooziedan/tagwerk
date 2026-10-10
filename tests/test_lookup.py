"""Looking up library tracks online: sure values become pending changes, nothing is written."""

import pytest
from sqlmodel import Session, select

from app import identify
from app.models import FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from tests.test_identify import web  # noqa: F401  (saved answers instead of the internet)

FIELDS_BEFORE = {"title": "Losing It", "artist": "Fisher", "duration": 248.0}


@pytest.fixture
def track(engine, settings, monkeypatch):
    """A library track known as "Fisher – Losing It" (4:08) with nothing else filled in."""
    monkeypatch.setattr(settings, "discogs_token", "test-token")
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        row = session.exec(select(Track).where(Track.path == "Unsorted/untagged.mp3")).one()
        for name, value in FIELDS_BEFORE.items():
            setattr(row, name, value)
        session.commit()
        return row.id


def pending(engine, track_id) -> dict[str, str]:
    with Session(engine) as session:
        rows = session.exec(select(PendingChange).where(PendingChange.track_id == track_id))
        return {r.field: r.new_value for r in rows}


def test_sure_values_become_pending_changes(web, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert staged["date"] == "2018-07-13"  # MusicBrainz, iTunes and Deezer agree on 2018
    assert staged["album"] == "Losing It"  # iTunes and Deezer agree
    assert "catalognumber" not in staged  # only Discogs knows it: check it on the track page
    assert (settings.music_dir / "Unsorted" / "untagged.mp3").exists()  # nothing written


def test_the_owners_pending_edits_are_kept(web, engine, settings, track):  # noqa: F811
    from app import changes

    with Session(engine) as session:
        changes.stage(session, [track], {"album": "My Album"})
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track)["album"] == "My Album"


def test_final_tracks_get_nothing_staged(web, engine, settings, track):  # noqa: F811
    with Session(engine) as session:
        row = session.get(Track, track)
        session.add(FinalTrack(track_id=track, mtime=row.mtime))
        session.commit()
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track) == {}
    with Session(engine) as session:  # the results are still there to look at
        assert any(f.best for f in identify.results(session, track, library=True))


def test_track_page_shows_results_and_stages_one(web, client, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    page = client.get(f"/tracks/{track}").text
    assert "Online sources" in page and "Open at Discogs" in page
    assert " data-remember>" in page and "online-remind" not in page  # no inbox reminder here
    client.post(f"/tracks/{track}/online", data={"source": "discogs", "n": "0"})
    staged = pending(engine, track)
    assert staged["catalognumber"] == "CATCH109" and staged["label"] == "Catch & Release"


def test_each_value_is_compared_with_the_file(web, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    with Session(engine) as session:
        row = session.get(Track, track)
        row.label, row.date = "catch & release", "2017"  # same label, spelled differently
        found = {f.source: f for f in identify.review(session, row, library=True)}
    discogs = {v.name: v for v in found["discogs"].fields[0]}
    assert discogs["label"].state == "same"
    assert discogs["catalognumber"].state == "new"  # the file has none
    assert discogs["date"].state == "differs" and discogs["date"].yours == "2017"
    assert found["discogs"].about  # each source says what it is good for


def test_look_up_ticked_tracks_from_the_list(web, client, engine, settings, track):  # noqa: F811
    from app.jobs import identify_job

    response = client.post("/tracks/lookup", data={"ids": [str(track)]}, follow_redirects=False)
    assert "looking=1" in response.headers["location"]
    identify_job.wait(30)
    assert pending(engine, track)["date"] == "2018-07-13"
    assert "Looking up 1 track online" in client.get(response.headers["location"]).text

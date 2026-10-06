"""MusicBrainz and Discogs ID fields: writing them, and fixing wrong values (app/ids.py)."""

import shutil

import pytest
from mutagen.flac import FLAC
from sqlmodel import Session, select

from app import changes, ids, writer
from app.changes import WriteProgress
from app.models import ChangeEntry, FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from tests.conftest import FIXTURES
from tests.test_writer import FORMATS, copy, raw

MBID = "0b6a4e7c-3a4f-4b8e-9d0e-1f2a3b4c5d6e"
OTHER = "11111111-1111-4111-8111-111111111111"
CHANGES = {
    "mb_trackid": MBID,
    "mb_albumid": None,
    "mb_artistid": f"{OTHER}; {MBID}",
    "discogs_releaseid": "25124086",
    "discogs_artistid": "1; 2",
}


# --- Writing ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_id_fields_round_trip_and_undo_exactly(tmp_path, fmt):
    path = copy(tmp_path, fmt)
    before = raw(path)
    snapshot = writer.write(path, CHANGES)
    info = read_file(path)
    assert (info.mb_trackid, info.mb_albumid) == (MBID, None)
    assert info.mb_artistid == f"{OTHER}; {MBID}"
    assert (info.discogs_releaseid, info.discogs_artistid) == ("25124086", "1; 2")
    assert not info.mbid_invalid
    writer.undo(path, snapshot)
    assert raw(path) == before


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("mb_albumid", f" {MBID.upper()} ", MBID),
        ("mb_artistid", f"{OTHER};{MBID}; {OTHER}", f"{OTHER}; {MBID}"),
        ("discogs_releaseid", "25124086", "25124086"),
        ("discogs_artistid", "", None),
    ],
)
def test_normalize_ids(field, value, expected):
    assert writer.normalize(field, value) == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [("mb_albumid", "25124086"), ("mb_trackid", f"{MBID}; {OTHER}"), ("discogs_releaseid", "r12")],
)
def test_normalize_rejects_wrong_ids(field, value):
    with pytest.raises(ValueError):
        writer.normalize(field, value)


# --- What is wrong, and the fix --------------------------------------------------------


def track(**values) -> Track:
    return Track(path="x.flac", format="flac", size=1, mtime=0, **values)


def test_discogs_numbers_move_to_their_own_fields():
    t = track(
        mb_trackid="25124086",
        mb_albumid="https://www.discogs.com/release/25124086-Fisher-Losing-It",
        mb_artistid=f"{MBID}; 123",
        mb_albumartistid="[a456]",
    )
    wrong = ids.wrong_ids(t)
    assert [(w.field, w.moves_to, w.number) for w in wrong] == [
        ("mb_trackid", "discogs_releaseid", "25124086"),
        ("mb_albumid", "discogs_releaseid", "25124086"),
        ("mb_artistid", "discogs_artistid", "123"),
        ("mb_albumartistid", "discogs_artistid", "456"),
    ]
    assert wrong[0].explanation == "Discogs number 25124086: moves to Discogs release ID"
    assert ids.fixes(t) == {
        "mb_trackid": None,
        "mb_albumid": None,
        "mb_artistid": MBID,  # the real MusicBrainz ID stays
        "mb_albumartistid": None,
        "discogs_releaseid": "25124086",  # once, though it came from two fields
        "discogs_artistid": "123; 456",
    }


def test_other_values_are_removed_and_existing_discogs_ids_kept():
    t = track(mb_albumid="unknown", mb_artistid="789", discogs_artistid="5")
    assert ids.wrong_ids(t)[0].explanation == "not an ID Tagwerk knows: removed"
    assert ids.fixes(t) == {"mb_albumid": None, "mb_artistid": None, "discogs_artistid": "5; 789"}


def test_nothing_to_fix():
    assert ids.fixes(track(mb_albumid=MBID)) == {}


# --- In the library --------------------------------------------------------------------

PATH = "Unsorted/discogs-ids.flac"  # musicbrainz_albumid = 25124086, like a tagger wrote it


@pytest.fixture
def wrong(engine, settings) -> int:
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        row = session.exec(select(Track).where(Track.path == PATH)).one()
        assert row.mbid_invalid
        return row.id


def test_fix_on_the_track_page_apply_and_undo(client, engine, settings, wrong):
    page = client.get(f"/tracks/{wrong}").text
    assert "Other values in MusicBrainz ID fields" in page
    assert "Discogs number 25124086: moves to Discogs release ID" in page

    response = client.post(f"/tracks/{wrong}/fix-ids", follow_redirects=False)
    assert response.headers["location"] == f"/tracks/{wrong}?saved=2"

    path = settings.music_dir / PATH
    before = dict(FLAC(path).tags)
    changes.apply_pending(engine, settings.music_dir, WriteProgress(action="apply"))
    tags = FLAC(path).tags
    assert "musicbrainz_albumid" not in tags and tags["discogs_release_id"] == ["25124086"]
    with Session(engine) as session:
        row = session.get(Track, wrong)
        assert not row.mbid_invalid and row.discogs_releaseid == "25124086"
        assert session.exec(select(ChangeEntry)).one().error is None  # reads back as written
        changeset = session.exec(select(ChangeEntry)).one().changeset_id
    changes.undo_changeset(engine, settings.music_dir, changeset, WriteProgress(action="undo"))
    assert dict(FLAC(path).tags) == before


def test_fix_all_flagged_tracks_from_the_list(client, engine, wrong):
    page = client.get("/tracks?flag=invalid_mbid").text
    assert "Fix IDs of 1 track" in page
    response = client.post(
        "/tracks/fix-ids?flag=invalid_mbid",
        data={"all": "true"},
        headers={"referer": "http://testserver/tracks?flag=invalid_mbid"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/tracks?flag=invalid_mbid&saved=2"
    with Session(engine) as session:
        staged = {c.field: c.new_value for c in session.exec(select(PendingChange))}
    assert staged == {"mb_albumid": None, "discogs_releaseid": "25124086"}


def test_final_tracks_are_not_fixed(client, engine, wrong):
    with Session(engine) as session:
        session.add(FinalTrack(track_id=wrong, mtime=session.get(Track, wrong).mtime))
        session.commit()
    assert "remove the final mark to fix them" in client.get(f"/tracks/{wrong}").text
    assert client.post("/api/tracks/fix-ids", json={"track_ids": [wrong]}).json() == {
        "pending_changes": 0
    }


def test_discogs_fields_are_read_and_named(tmp_path):
    path = tmp_path / "d.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    audio = FLAC(path)
    audio["DISCOGS_RELEASE_ID"] = "42"
    audio.save()
    assert read_file(path).discogs_releaseid == "42"
    from app.rawtags import used_as

    assert used_as("vorbis", "DISCOGS_RELEASE_ID") == "Discogs release ID"
    assert used_as("id3", "TXXX:DISCOGS_ARTIST_ID") == "Discogs artist ID"

"""MusicBrainz and Discogs IDs from the online lookup (ADR 0032): only sure IDs, only for empty
ID fields, through pending changes (library) or the import (inbox). Saved answers, no network."""

import pytest
from sqlmodel import Session, select

from app import changes, identify
from app.changes import WriteProgress
from app.models import FinalTrack, InboxTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.sources.base import Query, Source, SourceError
from tests.test_identify import (
    NAME,
    inbox_fixture,
    web,  # noqa: F401  (saved answers instead of the internet)
)

RECORDING = "cfff863a-7165-4e46-b632-262f77881753"  # Fisher – Losing It, 4:06 (MusicBrainz)
FISHER = "886dc0c9-3351-4d2d-b762-060cf1e66929"
RELEASE = "5b5e6d28-3e1f-4f0a-9a9b-0d1c2e3f4a5b"
OTHER = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def track(engine, settings, monkeypatch):
    """A library track known as "Fisher – Losing It" (4:08), with every source set up."""
    monkeypatch.setattr(settings, "acoustid_key", "test-key")
    monkeypatch.setattr(settings, "discogs_token", "test-token")
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        row = session.exec(select(Track).where(Track.path == "Unsorted/untagged.mp3")).one()
        row.title, row.artist, row.duration = "Losing It", "Fisher", 248.0
        session.commit()
        return row.id


@pytest.fixture
def inbox_track(engine, settings, monkeypatch):
    """An untagged inbox track named "Fisher - Losing It.mp3", 4:08 long."""
    return inbox_fixture(engine, settings, monkeypatch)


def set_tags(engine, track_id, **values):
    with Session(engine) as session:
        row = session.get(Track, track_id)
        for name, value in values.items():
            setattr(row, name, value)
        session.commit()


def pending(engine, track_id) -> dict[str, str]:
    with Session(engine) as session:
        rows = session.exec(select(PendingChange).where(PendingChange.track_id == track_id))
        return {r.field: r.new_value for r in rows}


def ids_of(staged: dict) -> dict:
    return {k: v for k, v in staged.items() if k.startswith(("mb_", "discogs_"))}


@pytest.fixture
def answers(web, monkeypatch):  # noqa: F811
    """Change the saved answers for one test: answers["acoustid"] = function(data)."""
    changes_ = {}
    saved = Source.get_json

    def get_json(self, url, params=None, headers=None):
        data = saved(self, url, params, headers)
        for part, change in changes_.items():
            if part in url:
                change(data)
        return data

    monkeypatch.setattr(Source, "get_json", get_json)
    return changes_


def own_release(data):
    """MusicBrainz knows the 4:06 recording's own single (not only compilations)."""
    for recording in data.get("recordings", []):
        if recording["id"] == RECORDING:
            recording["releases"].append(
                {"id": RELEASE, "title": "Losing It", "status": "Official", "date": "2018-07-13",
                 "artist-credit": [{"name": "Fisher", "artist": {"id": FISHER}}],
                 "release-group": {"primary-type": "Single", "secondary-types": []}}
            )  # fmt: skip


# --- The sources ---------------------------------------------------------------------------


def test_sources_hand_over_the_ids_they_get(web, settings):  # noqa: F811
    from app.sources.acoustid import AcoustID
    from app.sources.discogs import Discogs
    from app.sources.musicbrainz import MusicBrainz

    query = Query("Fisher", "Losing It", 248.0, settings.music_dir / "x.mp3")
    key = settings.model_copy(update={"acoustid_key": "k", "discogs_token": "t"})
    mb = {c.values["mb_trackid"]: c for c in MusicBrainz(key).lookup(query)}[RECORDING]
    assert mb.values["mb_artistid"] == FISHER and "mb_albumid" not in mb.values  # compilations
    heard = AcoustID(key).lookup(query)[0]
    assert (heard.values["mb_trackid"], heard.values["mb_artistid"]) == (RECORDING, FISHER)
    discogs = Discogs(key)
    assert discogs.lookup(query)[0].values["discogs_releaseid"] == "12345"
    release = discogs.release("12345")
    assert release.artist_ids == "4089851"
    assert release.tracks == [("1", "Losing It", 248.0), ("2", "Losing It (Radio Edit)", 163.0)]
    assert MusicBrainz(key).discogs_release(RELEASE) == "12345"


# --- Library tracks: sure IDs become pending changes -------------------------------------------


def test_recognised_audio_gives_the_recording_and_artist_ids(web, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    staged = ids_of(pending(engine, track))
    # AcoustID recognised the sound (96 %) and MusicBrainz names the same recording. It is only
    # on compilations there, so no album ID; Discogs' label and catalog number agree with nothing.
    assert staged == {"mb_trackid": RECORDING, "mb_artistid": FISHER}
    with Session(engine) as session:
        where = PendingChange.field == "mb_trackid"
        change = session.exec(select(PendingChange).where(where)).one()
        assert change.source == "online" and change.old_value is None
    assert (settings.music_dir / "Unsorted" / "untagged.mp3").exists()  # nothing written


def test_the_album_ids_come_with_the_tracks_own_release(answers, engine, settings, track):
    answers["musicbrainz.org/ws/2/recording"] = own_release
    identify.lookup(engine, settings, track, library=True)
    staged = ids_of(pending(engine, track))
    assert staged["mb_albumid"] == RELEASE and staged["mb_albumartistid"] == FISHER
    # The MusicBrainz release links to Discogs release 12345: the Discogs IDs are sure too,
    # and the track is number 1 on it (the 4:08 one, not the radio edit).
    assert staged["discogs_releaseid"] == "12345" and staged["discogs_artistid"] == "4089851"
    assert staged["discogs_trackid"] == "12345-1"


def test_a_pending_album_counts_as_the_tracks_album(answers, engine, settings, track):
    """Looked up before: the album is waiting as a pending change; looking up again (now with
    IDs) still knows it is the track's album."""
    answers["musicbrainz.org/ws/2/recording"] = own_release
    with Session(engine) as session:
        changes.stage(session, [track], {"album": "Losing It"}, "online")
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track)["mb_albumid"] == RELEASE


def test_no_album_id_for_another_album(answers, engine, settings, track):
    answers["musicbrainz.org/ws/2/recording"] = own_release
    set_tags(engine, track, album="The Annual 2019")
    identify.lookup(engine, settings, track, library=True)
    assert "mb_albumid" not in pending(engine, track)


def test_two_sources_on_the_title_are_not_enough(answers, engine, settings, track):
    def unclear_other_recording(data):
        data["results"][0]["score"] = 0.8
        data["results"][0]["recordings"][0]["id"] = OTHER

    answers["acoustid.org"] = unclear_other_recording
    identify.lookup(engine, settings, track, library=True)
    assert not {"mb_trackid", "mb_artistid"} & set(pending(engine, track))


def test_an_unclear_sound_with_musicbrainz_agreeing_is_sure(answers, engine, settings, track):
    answers["acoustid.org"] = lambda data: data["results"][0].update(score=0.8)
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track)["mb_trackid"] == RECORDING
    with Session(engine) as session:
        row = session.get(Track, track)
        proposals = identify.id_suggestions(session, row, {}, {}, library=True)
    assert {p.reason for p in proposals if p.field == "mb_trackid"} == {
        "AcoustID + MusicBrainz agree"
    }


def test_musicbrainz_alone_gives_no_ids(web, engine, settings, track, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "acoustid_key", "")  # AcoustID not set up
    identify.lookup(engine, settings, track, library=True)
    assert not ids_of(pending(engine, track))


def test_existing_ids_are_never_replaced(web, engine, settings, track):  # noqa: F811
    set_tags(engine, track, mb_trackid=OTHER)
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert "mb_trackid" not in staged and staged["mb_artistid"] == FISHER  # empty: filled


def test_wrong_values_in_musicbrainz_fields_wait_for_fix_ids(web, engine, settings, track):  # noqa: F811
    set_tags(engine, track, mb_albumid="25124086", mbid_invalid=True)  # a Discogs number
    identify.lookup(engine, settings, track, library=True)
    assert not {k for k in pending(engine, track) if k.startswith("mb_")}


def test_final_tracks_get_no_ids(web, engine, settings, track):  # noqa: F811
    with Session(engine) as session:
        session.add(FinalTrack(track_id=track, mtime=session.get(Track, track).mtime))
        session.commit()
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track) == {}


def test_discogs_ids_when_album_and_label_agree(web, engine, settings, track):  # noqa: F811
    set_tags(engine, track, label="Catch & Release")
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert staged["discogs_releaseid"] == "12345" and staged["discogs_artistid"] == "4089851"


def pressings(data):
    """Discogs finds the digital single and a vinyl pressing of the same track."""
    vinyl = dict(data["results"][0], id=67890, catno="CATCH109V", uri="/release/67890")
    data["results"].append(vinyl)


def test_of_several_pressings_the_catalog_number_decides(answers, engine, settings, track):
    answers["discogs.com/database/search"] = pressings
    set_tags(engine, track, label="Catch & Release", catalognumber="CATCH-109")
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track)["discogs_releaseid"] == "12345"


def test_several_pressings_without_a_clear_winner_give_no_id(answers, engine, settings, track):
    answers["discogs.com/database/search"] = pressings
    set_tags(engine, track, label="Catch & Release")  # both pressings have this label
    identify.lookup(engine, settings, track, library=True)
    assert "discogs_releaseid" not in pending(engine, track)


def test_a_failed_id_request_only_leaves_that_id_out(web, engine, settings, track, monkeypatch):  # noqa: F811
    from app.sources.discogs import Discogs

    def busy(self, release_id):
        raise SourceError("Discogs is busy (rate limit); tried again later")

    monkeypatch.setattr(Discogs, "release", busy)
    set_tags(engine, track, label="Catch & Release")
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert staged["discogs_releaseid"] == "12345"
    assert "discogs_artistid" not in staged and "discogs_trackid" not in staged
    assert staged["mb_trackid"] == RECORDING


# --- The track page and the Changes page --------------------------------------------------------


def test_track_page_links_the_ids_and_takes_them(web, client, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    page = client.get(f"/tracks/{track}").text
    assert f"https://musicbrainz.org/recording/{RECORDING}" in page
    assert "https://www.discogs.com/release/12345" in page and "IDs only fill empty" in page
    assert '<details class="online-src is-match" open>' in page  # each source folds on its own
    client.post(f"/tracks/{track}/online", data={"source": "discogs", "n": "0"})
    staged = pending(engine, track)
    assert staged["discogs_releaseid"] == "12345" and staged["discogs_artistid"] == "4089851"


def test_use_these_values_leaves_existing_ids_alone(web, client, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    with Session(engine) as session:
        changes.discard(session)
    set_tags(engine, track, mb_trackid=OTHER)
    client.post(f"/tracks/{track}/online", data={"source": "acoustid", "n": "0"})
    staged = pending(engine, track)
    assert "mb_trackid" not in staged and staged["mb_artistid"] == FISHER


def test_changes_page_shows_ids_as_links(web, client, engine, settings, track):  # noqa: F811
    identify.lookup(engine, settings, track, library=True)
    page = client.get("/changes").text
    assert "MusicBrainz track ID" in page and "Found online" in page
    assert f'href="https://musicbrainz.org/recording/{RECORDING}"' in page
    assert f'href="https://musicbrainz.org/artist/{FISHER}"' in page


def test_applied_ids_are_written_and_undone(web, engine, settings, track):  # noqa: F811
    from app.models import ChangeSet
    from app.tags import read_file

    identify.lookup(engine, settings, track, library=True)
    path = settings.music_dir / "Unsorted" / "untagged.mp3"
    changes.apply_pending(engine, settings.music_dir, WriteProgress())
    info = read_file(path)
    assert (info.mb_trackid, info.mb_artistid) == (RECORDING, FISHER)
    with Session(engine) as session:
        changeset = session.exec(select(ChangeSet)).one()
    changes.undo_changeset(engine, settings.music_dir, changeset.id, WriteProgress(action="undo"))
    info = read_file(path)
    assert (info.mb_trackid, info.mb_artistid) == (None, None)


# --- Inbox tracks: written on import -----------------------------------------------------------


def test_inbox_import_writes_sure_ids_into_empty_fields(web, client, engine, settings, inbox_track):  # noqa: F811
    from app.importer import import_tracks, plan
    from app.tags import read_file

    identify.lookup(engine, settings, inbox_track)
    with Session(engine) as session:
        item = plan(session, session.get(InboxTrack, inbox_track), settings.music_dir)
    assert item.changes["mb_trackid"] == RECORDING and item.sources["mb_trackid"] == "online"
    assert item.changes["mb_artistid"] == FISHER
    page = client.get(f"/inbox/{inbox_track}").text
    assert "IDs found online" in page and "AcoustID + MusicBrainz agree" in page

    progress = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, [inbox_track], progress)
    assert progress.written == 1, progress.errors
    with Session(engine) as session:
        row = session.exec(select(Track).where(Track.path.endswith(NAME))).one()
    assert read_file(settings.music_dir / row.path).mb_trackid == RECORDING


def test_inbox_ids_already_in_the_file_stay(web, engine, settings, inbox_track):  # noqa: F811
    from app import writer
    from app.importer import plan

    writer.write(settings.import_dir / NAME, {"mb_trackid": OTHER})
    identify.lookup(engine, settings, inbox_track)
    with Session(engine) as session:
        item = plan(session, session.get(InboxTrack, inbox_track), settings.music_dir)
    assert "mb_trackid" not in item.changes and item.changes["mb_artistid"] == FISHER


def test_inbox_use_these_values_takes_the_ids(web, client, engine, settings, inbox_track):  # noqa: F811
    from app.importer import plan

    identify.lookup(engine, settings, inbox_track)
    client.post(f"/inbox/{inbox_track}/online", data={"source": "discogs", "n": "0"})
    with Session(engine) as session:
        item = plan(session, session.get(InboxTrack, inbox_track), settings.music_dir)
    assert item.changes["discogs_releaseid"] == "12345"
    assert item.sources["discogs_releaseid"] == "you"  # the owner took this result over
    assert item.changes["discogs_artistid"] == "4089851"


# --- Discogs track IDs (ADR 0033) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("tracks", "duration", "expected"),
    [
        ([("1", "Losing It", 248.0), ("2", "Losing It (Radio Edit)", 163.0)], 248.0, "1"),
        ([("A1", "Losing It (Original Mix)", 247.0)], 248.0, "A1"),  # another version, same length
        ([("1", "Losing It (Original Mix)", None)], 248.0, None),  # no length: exact title only
        ([("1", "Losing It", None)], 248.0, "1"),
        ([("1", "Losing It", 401.0)], 248.0, None),  # a different edit
        ([("1", "Losing It", 248.0), ("7", "Losing It", 249.0)], 248.0, None),  # which one?
        ([("1", "Something Else", 248.0)], 248.0, None),
    ],
)  # fmt: skip
def test_the_track_is_found_in_the_discogs_tracklist(tracks, duration, expected):
    assert identify._discogs_track(tracks, Query("Fisher", "Losing It", duration)) == expected


def test_discogs_track_id_comes_with_the_sure_release(web, engine, settings, track):  # noqa: F811
    set_tags(engine, track, label="Catch & Release")
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert staged["discogs_releaseid"] == "12345" and staged["discogs_trackid"] == "12345-1"

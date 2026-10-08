import shutil
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, select

from app import duplicates, trash
from app.duplicates import LibraryIndex, main_artist, normalized
from app.inbox import save_values, scan_inbox
from app.models import InboxTrack, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES

# In the test library (tests/conftest.py): "Artist One; Artist Two - Silent Track", MBID 1111…
LIBRARY_COPY = "Fixture Artist/Fixture Album/tagged.mp3"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Losing It (Extended Mix)", "losing it  (extended mix)"),
        ("Beyoncé & JAY-Z", "Beyonce and Jay Z"),
        ("Turn Back Time (feat. Kele)", "Turn Back Time"),
        ("Turn Back Time ft. Kele", "Turn Back Time"),
    ],
)
def test_spelling_is_evened_out(a, b):
    assert normalized(a) == normalized(b)


def test_the_mix_name_counts():
    assert normalized("Losing It (Extended Mix)") != normalized("Losing It (Jus Ron Edit)")


def test_only_the_first_artist_counts():
    assert main_artist("Fisher; Kita Alexander") == main_artist("FISHER & Kita Alexander")
    assert main_artist("Fisher ft. Kita Alexander") == "fisher"


@pytest.fixture
def library(engine, settings):
    scan_library(engine, settings.music_dir, ScanProgress())
    settings.import_dir.mkdir()
    return settings.import_dir


def add_to_inbox(engine, inbox, fixture, name, values=None) -> int:
    shutil.copy(FIXTURES / fixture, inbox / name)
    scan_inbox(engine, inbox, ScanProgress())
    with Session(engine) as session:
        track = session.exec(select(InboxTrack).where(InboxTrack.path == name)).one()
        if values:
            save_values(session, track, values)
        return track.id


def matches(engine, settings, track_id, title=None, artist=None):
    with Session(engine) as session:
        track = session.get(InboxTrack, track_id)
        index = LibraryIndex.load(session)
        found = index.matches(track, title, artist, settings.import_dir, settings.music_dir)
        return [(m.track.path, m.reason) for m in found]


def test_an_identical_file_is_found(engine, settings, library):
    track_id = add_to_inbox(engine, library, "tagged.mp3", "again.mp3")
    assert (LIBRARY_COPY, "identical file") in matches(engine, settings, track_id)


def test_the_same_musicbrainz_recording_is_found(engine, settings, library):
    track_id = add_to_inbox(engine, library, "tagged.flac", "other format.flac")
    found = dict(matches(engine, settings, track_id, "Other Title", "Artist One"))
    assert found[LIBRARY_COPY] == "same MusicBrainz recording"


def test_a_musicbrainz_id_on_another_artist_is_not_trusted(engine, settings, library):
    track_id = add_to_inbox(engine, library, "tagged.flac", "other format.flac")
    found = dict(matches(engine, settings, track_id, "Something Else", "Somebody Else"))
    assert LIBRARY_COPY not in found  # same (wrong) ID, but a different artist


def test_a_musicbrainz_id_shared_by_several_artists_is_not_trusted(engine, settings, library):
    with Session(engine) as session:  # the same ID on a track by someone else
        other = session.exec(select(Track).where(Track.path.endswith("tagged.wav"))).one()
        other.artist = "Somebody Else"
        session.commit()
    track_id = add_to_inbox(engine, library, "tagged.flac", "no artist known.flac")
    assert LIBRARY_COPY not in dict(matches(engine, settings, track_id))


def test_a_musicbrainz_id_on_several_titles_is_not_trusted(engine, settings, library):
    with Session(engine) as session:  # one ID copied onto every track of an EP
        other = session.exec(select(Track).where(Track.path.endswith("tagged.wav"))).one()
        other.title = "Track 2"
        session.commit()
    track_id = add_to_inbox(engine, library, "tagged.flac", "copy.flac")
    found = dict(matches(engine, settings, track_id, "Other Title", "Artist One"))
    assert LIBRARY_COPY not in found


def test_the_same_artist_and_title_is_found(engine, settings, library):
    track_id = add_to_inbox(engine, library, "untagged.mp3", "download.mp3")
    title, artist = "silent track", "Artist One & Someone"  # spelled differently
    found = dict(matches(engine, settings, track_id, title, artist))
    assert found[LIBRARY_COPY] == "same artist and title"


def test_other_mixes_and_lengths_are_not_duplicates(engine, settings, library):
    track_id = add_to_inbox(engine, library, "untagged.mp3", "download.mp3")

    def by_name(title):
        found = matches(engine, settings, track_id, title, "Artist One")
        return [path for path, reason in found if reason == "same artist and title"]

    assert by_name("Silent Track (Extended Mix)") == []
    with Session(engine) as session:
        session.get(InboxTrack, track_id).duration = 300  # same name, much longer: another edit
        session.commit()
    assert by_name("Silent Track") == []


# --- Trash -------------------------------------------------------------------------------------


def test_trash_keeps_the_path_and_restores_it(tmp_path):
    (tmp_path / "Promos").mkdir()
    (tmp_path / "Promos" / "a.mp3").write_bytes(b"audio")
    entry = trash.delete(tmp_path, "Promos/a.mp3")
    assert not (tmp_path / "Promos" / "a.mp3").exists()
    [item] = trash.items(tmp_path)
    assert (item.id, item.path, item.size) == (entry, "Promos/a.mp3", 5)

    assert trash.restore(tmp_path, entry) == "Promos/a.mp3"
    assert (tmp_path / "Promos" / "a.mp3").read_bytes() == b"audio"
    assert trash.items(tmp_path) == []


def test_restore_never_overwrites(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"old")
    entry = trash.delete(tmp_path, "a.mp3")
    (tmp_path / "a.mp3").write_bytes(b"new download")
    with pytest.raises(trash.TrashError, match="in the inbox again"):
        trash.restore(tmp_path, entry)
    assert (tmp_path / "a.mp3").read_bytes() == b"new download"


def test_files_are_removed_for_good_after_30_days(tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"audio")
    trash.delete(tmp_path, "a.mp3")
    assert trash.purge(tmp_path, datetime.now(UTC) + timedelta(days=29)) == 0
    assert trash.purge(tmp_path, datetime.now(UTC) + timedelta(days=31)) == 1
    assert trash.items(tmp_path) == []


def test_only_inbox_files_can_be_deleted(tmp_path):
    inbox = tmp_path / "import"
    inbox.mkdir()
    (tmp_path / "library.mp3").write_bytes(b"audio")
    with pytest.raises(trash.TrashError):
        trash.delete(inbox, "../library.mp3")
    assert (tmp_path / "library.mp3").exists()


# --- Pages -------------------------------------------------------------------------------------


def test_duplicates_are_shown_and_can_be_moved_to_the_trash(client, engine, settings, library):
    track_id = add_to_inbox(engine, library, "tagged.mp3", "again.mp3")
    add_to_inbox(engine, library, "untagged.mp3", "new track.mp3")

    page = client.get("/inbox").text
    assert "In library" in page and 'data-view="duplicates"' in page
    review = client.get(f"/inbox/{track_id}").text
    assert "Already in your library?" in review and LIBRARY_COPY in review
    duplicate = next(t for t in client.get("/api/inbox").json() if t["id"] == track_id)
    assert LIBRARY_COPY in [d["path"] for d in duplicate["duplicates"]]

    response = client.post(f"/inbox/{track_id}/delete", data={"show": "all"})
    assert response.status_code == 200  # followed to the next track
    assert not (library / "again.mp3").exists()
    assert (settings.music_dir / LIBRARY_COPY).exists()  # the library copy is never touched
    assert [t["path"] for t in client.get("/api/inbox").json()] == ["new track.mp3"]

    [deleted] = client.get("/api/inbox/trash").json()
    assert deleted["path"] == "again.mp3"
    assert "Recently deleted" in client.get("/inbox").text

    client.post(f"/inbox/trash/{deleted['id']}/restore")
    assert (library / "again.mp3").exists()
    assert len(client.get("/api/inbox").json()) == 2  # back in the list right away


def test_several_tracks_can_be_deleted_from_the_list(client, engine, library):
    ids = [add_to_inbox(engine, library, "untagged.mp3", f"{n}.mp3") for n in ("a", "b", "c")]
    page = client.post("/inbox/delete", data={"ids": [str(i) for i in ids[:2]]}).text
    assert "Moved 2 files to the trash" in page
    assert [t["path"] for t in client.get("/api/inbox").json()] == ["c.mp3"]
    assert sorted(d["path"] for d in client.get("/api/inbox/trash").json()) == ["a.mp3", "b.mp3"]


def test_delete_api(client, engine, library):
    track_id = add_to_inbox(engine, library, "untagged.mp3", "a.mp3")
    assert client.delete(f"/api/inbox/{track_id}").json() == {"deleted": 1}
    assert client.delete(f"/api/inbox/{track_id}").status_code == 404


def test_automatic_import_leaves_duplicates_for_the_owner(client, settings, library):
    import os
    import time

    from app.jobs import inbox_job

    shutil.copy(FIXTURES / "tagged.mp3", library / "complete but known.mp3")
    old = time.time() - 600
    os.utime(library / "complete but known.mp3", (old, old))
    prefs = client.get("/api/settings").json() | {"automation": "auto"}
    client.put("/api/settings", json=prefs)
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    assert [t["path"] for t in client.get("/api/inbox").json()] == ["complete but known.mp3"]


# --- Duplicates inside the library (ADR 0022) ----------------------------------------------


def _library_track(id, title="Losing It", artist="Fisher", duration=300.0, size=None, mbid=None):
    return Track(id=id, path=f"x/{id}.mp3", format="mp3", size=size or 1000 + id, mtime=0,
                 duration=duration, title=title, artist=artist, mb_trackid=mbid)  # fmt: skip


def test_library_links_follow_the_inbox_rules(tmp_path):
    tracks = [
        _library_track(1),
        _library_track(2, artist="FISHER & Kita Alexander", duration=301.5),  # same track
        _library_track(3, duration=180.0),  # radio edit: a different length
        _library_track(4, title="Losing It (Extended Mix)"),  # another mix
        _library_track(5, title="Other", artist="Someone", mbid="ABC"),
        _library_track(6, title="Different", artist="Else", mbid="abc"),  # ID copied onto an EP
    ]
    links = duplicates.library_links(tracks, tmp_path, apart=set())
    assert links == [(1, 2, "name")]
    assert duplicates.library_links(tracks, tmp_path, apart={(1, 2)}) == []


def test_a_trusted_musicbrainz_id_links_tracks_without_names(tmp_path):
    tracks = [_library_track(1, None, None, mbid="ID"), _library_track(2, None, None, mbid="id")]
    assert duplicates.library_links(tracks, tmp_path, set()) == [(1, 2, "mbid")]


def test_groups_join_copies_linked_through_another_copy():
    groups = duplicates.library_groups([(1, 2, "name"), (2, 3, "file"), (7, 8, "mbid")])
    assert groups == {1: (1, "name"), 2: (1, "file"), 3: (1, "file"), 7: (7, "mbid"),
                      8: (7, "mbid")}  # fmt: skip


def scan_job_run(client):
    from app.jobs import scan_job

    client.post("/api/scan")
    scan_job.wait(30)


def test_library_duplicates_after_a_scan(client, music_dir):
    # An identical copy of an untagged file in another folder: found by its content.
    shutil.copy(music_dir / "Unsorted" / "untagged.mp3", music_dir / "Info Artist" / "copy.mp3")
    scan_job_run(client)
    groups = {tuple(sorted(t["path"] for t in g["tracks"])): g for g in client.get(
        "/api/duplicates").json()}  # fmt: skip
    identical = groups[("Info Artist/copy.mp3", "Unsorted/untagged.mp3")]
    assert identical["reasons"] == ["file"]
    # The test library's "Silent Track" in seven formats: the same recording (one MBID).
    formats = next(g for g in groups.values() if len(g["tracks"]) == 7)
    assert formats["reasons"] == ["mbid"]
    assert sum(t["best_sound"] for t in formats["tracks"]) <= 1

    # Every number points at the same tracks.
    listed = client.get("/api/tracks", params={"flag": "duplicate"}).json()["total"]
    assert listed == 9
    page = client.get("/duplicates").text
    assert "Tracks with copies" in page and "Silent Track" in page
    assert "2 tracks in the library more than once" in client.get("/").text
    assert "9 files</a> are copies of 2 tracks" in client.get("/stats").text

    # The track page links to its group.
    track = identical["tracks"][0]["id"]
    assert f"/duplicates?group={identical['group']}" in client.get(f"/tracks/{track}").text

    # Keep them all: the group is gone, and comes back on request.
    ids = [t["id"] for t in identical["tracks"]]
    client.post("/duplicates/keep", data={"track_ids": ids})
    assert len(client.get("/api/duplicates").json()) == 1
    assert client.get("/api/tracks", params={"flag": "duplicate"}).json()["total"] == 7
    scan_job_run(client)  # a scan doesn't bring it back
    assert len(client.get("/api/duplicates").json()) == 1
    assert client.post("/api/duplicates/show-again").json() == {"forgotten_pairs": 1, "groups": 2}

    # Deleting a copy in the file manager: the next scan notices.
    (music_dir / "Info Artist" / "copy.mp3").unlink()
    scan_job_run(client)
    assert len(client.get("/api/duplicates").json()) == 1


def test_no_duplicates_page(client):
    assert "No duplicates." in client.get("/duplicates").text

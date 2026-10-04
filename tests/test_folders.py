import shutil
from dataclasses import replace

import pytest
from sqlmodel import Session, select

from app import folders, preferences
from app.changes import WriteProgress, undo_changeset
from app.importer import plan
from app.inbox import save_values, scan_inbox
from app.models import ChangeSet, InboxTrack, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES


@pytest.fixture
def unsorted(engine, settings):
    """Two "Electronic" tracks (one with lyrics) and one without a genre in _Unsorted."""
    root = settings.music_dir / "_Unsorted"
    root.mkdir()
    shutil.copy(FIXTURES / "tagged.mp3", root / "song.mp3")
    shutil.copy(FIXTURES / "tagged.flac", root / "tagged.flac")
    shutil.copy(FIXTURES / "untagged.mp3", root / "untagged.mp3")
    (root / "song.lrc").write_text("[00:01.00] la la")
    scan_library(engine, settings.music_dir, ScanProgress())
    set_prefs(engine, genre_folders=["House"])
    return root


def set_prefs(engine, **values):
    with Session(engine) as session:
        preferences.save(session, replace(preferences.load(session), **values))


def get_prefs(engine):
    with Session(engine) as session:
        return preferences.load(session)


def proposals(engine, settings):
    with Session(engine) as session:
        return folders.proposals(session, settings.music_dir)


def create(engine, settings, genre="Electronic") -> WriteProgress:
    progress = WriteProgress(action="folder")
    folders.create_folder(engine, settings.music_dir, genre, progress)
    return progress


def test_tracks_in_unsorted_are_proposed_per_genre(engine, settings, unsorted):
    [proposal] = proposals(engine, settings)  # the track without a genre isn't proposed
    assert (proposal.genre, proposal.folder, proposal.exists) == ("Electronic", "Electronic", False)
    assert [(m.track.path, m.target) for m in proposal.moves] == [
        ("_Unsorted/song.mp3", "Electronic/song.mp3"),
        ("_Unsorted/tagged.flac", "Electronic/tagged.flac"),
    ]
    assert not (settings.music_dir / "Electronic").exists()  # proposing changes nothing


def test_creating_moves_files_unrenamed_and_undo_puts_everything_back(engine, settings, unsorted):
    before = (unsorted / "song.mp3").read_bytes()
    progress = create(engine, settings)
    assert (progress.written, progress.failed) == (2, 0)

    new = settings.music_dir / "Electronic"
    assert sorted(p.name for p in new.iterdir()) == ["song.lrc", "song.mp3", "tagged.flac"]
    assert (new / "song.mp3").read_bytes() == before  # moved, not rewritten
    assert sorted(p.name for p in unsorted.iterdir()) == ["untagged.mp3"]
    with Session(engine) as session:
        paths = {t.path for t in session.exec(select(Track))}
        assert {"Electronic/song.mp3", "Electronic/tagged.flac"} <= paths
        assert session.exec(select(ChangeSet)).one().kind == "folder"
    assert get_prefs(engine).genre_folders == ["House", "Electronic"]  # later imports go there
    assert proposals(engine, settings) == []

    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id
    progress = WriteProgress(action="undo")
    undo_changeset(engine, settings.music_dir, changeset_id, progress)
    assert (progress.written, progress.failed) == (2, 0)
    assert not new.exists()  # the folder Tagwerk created is gone again
    assert (unsorted / "song.mp3").read_bytes() == before
    assert (unsorted / "song.lrc").exists()
    assert get_prefs(engine).genre_folders == ["House"]
    with Session(engine) as session:
        assert "_Unsorted/song.mp3" in {t.path for t in session.exec(select(Track))}


def test_existing_files_are_never_overwritten(engine, settings, unsorted):
    existing = settings.music_dir / "Electronic" / "song.mp3"
    existing.parent.mkdir()
    existing.write_bytes(b"already here")
    [proposal] = proposals(engine, settings)
    assert proposal.exists  # only the files move

    progress = create(engine, settings)
    assert (progress.written, progress.failed) == (1, 1)
    assert "already exists" in progress.errors[0]
    assert existing.read_bytes() == b"already here"
    assert (unsorted / "song.mp3").exists() and (unsorted / "song.lrc").exists()

    with Session(engine) as session:  # undo keeps the folder: it was there before
        changeset_id = session.exec(select(ChangeSet)).one().id
    undo_changeset(engine, settings.music_dir, changeset_id, WriteProgress(action="undo"))
    assert existing.read_bytes() == b"already here"


def test_kept_genres_are_not_proposed_again(engine, settings, unsorted):
    with Session(engine) as session:
        folders.keep_unsorted(session, "Electronic")
    assert proposals(engine, settings) == []
    with Session(engine) as session:
        folders.keep_unsorted(session, None)  # "Propose folders again"
    assert len(proposals(engine, settings)) == 1


def test_no_proposals_for_other_layouts(engine, settings, unsorted):
    set_prefs(engine, folder_layout="artist")
    assert proposals(engine, settings) == []


def test_a_new_genre_waits_in_unsorted_until_the_owner_agrees(client, engine, settings):
    """The whole flow: import a Rock track, review the proposal on the Changes page, apply."""
    from app.jobs import write_job

    settings.import_dir.mkdir()
    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / "Band - Song.mp3")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        track = session.exec(select(InboxTrack)).one()
        save_values(session, track, {"genre": "Rock"})
        item = plan(session, track, settings.music_dir)
        assert (item.destination, item.new_genre) == ("_Unsorted/Band - Song.mp3", "Rock")
        track_id = track.id
    assert "Rock has no folder yet" in client.get(f"/inbox/{track_id}").text

    client.post("/inbox/import", data={"ids": [str(track_id)]})
    write_job.wait(30)
    assert (settings.music_dir / "_Unsorted" / "Band - Song.mp3").exists()
    assert not (settings.music_dir / "Rock").exists()  # not without the owner's OK

    page = client.get("/changes").text
    assert "New folder <code>Rock/</code>" in page
    assert "_Unsorted/Band - Song.mp3" in page and "Rock/Band - Song.mp3" in page
    assert client.get("/api/folders").json()[0]["moves"][0]["to"] == "Rock/Band - Song.mp3"

    client.post("/changes/folders/create", data={"genre": "Rock"})
    write_job.wait(30)
    assert (settings.music_dir / "Rock" / "Band - Song.mp3").exists()
    assert "New folder" not in client.get("/changes").text
    assert "Moved" in client.get(f"/changes/history/{write_job.progress.changeset_id}").text


def test_keep_in_unsorted_from_the_changes_page(client, engine, settings, unsorted):
    client.post("/changes/folders/keep", data={"genre": "Electronic"})
    page = client.get("/changes").text
    assert "New folder" not in page and "Kept in <code>_Unsorted</code>" in page
    client.post("/changes/folders/propose-again")
    assert "New folder <code>Electronic/</code>" in client.get("/changes").text

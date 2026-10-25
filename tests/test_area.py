"""The Releasomat area kept out of the library (ADR 0044, step 1): the folder checks, the scan
that skips it, the guards that never let Tagwerk act there, and Settings → Releasomat."""

import json
import shutil
from dataclasses import replace

import pytest
from mutagen.flac import FLAC
from sqlmodel import Session, select

from app import area, folders, naming, preferences
from app.changes import WriteProgress, apply_pending
from app.config import get_settings
from app.duplicates import restore_copy
from app.importer import plan
from app.inbox import scan_inbox
from app.jobs import scan_job
from app.models import (
    ChangeEntry,
    ChangeSet,
    DuplicateTrack,
    FinalTrack,
    InboxTrack,
    Notification,
    PendingChange,
    SecretTrack,
    Track,
)
from app.scanner import EmptyLibraryError, ScanProgress, scan_library
from app.undo import undo_changeset
from tests.conftest import FIXTURES

AREA = "Releasomat"
DOWNLOADS = ["Someone/tagged.mp3", "Someone/tagged.flac", "Other/untagged.mp3"]
LIBRARY = 10  # audio files in the test library outside the area (conftest.music_dir)


@pytest.fixture
def downloads(music_dir):
    """Three Releasomat downloads in /music/Releasomat."""
    for rel in DOWNLOADS:
        target = music_dir / AREA / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / rel.split("/")[-1], target)
    return music_dir / AREA


def scan(engine, music_dir, skip=()) -> ScanProgress:
    progress = ScanProgress()
    scan_library(engine, music_dir, progress, skip)
    return progress


def paths(engine) -> set[str]:
    with Session(engine) as session:
        return set(session.exec(select(Track.path)))


def set_prefs(engine, **values):
    with Session(engine) as session:
        preferences.save(session, replace(preferences.load(session), **values))


def prefs(engine):
    with Session(engine) as session:
        return preferences.load(session)


def area_ids(engine) -> list[int]:
    with Session(engine) as session:
        return area.area_track_ids(session, AREA)


# --- The folder's checks ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, problem",
    [
        ("", "No folder"),
        (".", "whole music folder"),
        ("/", "isn't inside"),
        ("..", "outside"),
        ("Releasomat/../..", "outside"),
        ("/elsewhere/Releasomat", "isn't inside"),
        (".hidden", "hidden"),
        ("@eaDir", "hidden"),
        ("_Unsorted", "_Unsorted"),
        ("_Unsorted/Releasomat", "_Unsorted"),
        ("House", "genre folders"),
        ("Missing", "There is no folder"),
    ],
)
def test_a_folder_that_cant_be_the_area_is_refused(settings, music_dir, name, problem):
    for folder in (".hidden", "@eaDir", "_Unsorted/Releasomat", "House"):
        (music_dir / folder).mkdir(parents=True)
    with pytest.raises(area.FolderProblem, match=problem):
        area.check_folder(name, settings, preferences.Preferences(genre_folders=["House"]))


@pytest.mark.parametrize(
    "name, folder",
    [
        ("Releasomat", "Releasomat"),
        (" Releasomat/ ", "Releasomat"),
        ("./Releasomat", "Releasomat"),
        ("Downloads/Releasomat", "Downloads/Releasomat"),
        ("Downloads\\Releasomat", "Downloads/Releasomat"),
    ],
)
def test_the_area_may_be_nested_and_written_in_several_ways(settings, music_dir, name, folder):
    (music_dir / "Releasomat").mkdir()
    (music_dir / "Downloads" / "Releasomat").mkdir(parents=True)
    assert area.check_folder(name, settings, preferences.Preferences()) == folder
    absolute = f"{music_dir.as_posix()}/{folder}"
    assert area.check_folder(absolute, settings, preferences.Preferences()) == folder


# --- The scan ---------------------------------------------------------------------------------


def test_files_in_the_kept_out_folder_never_become_tracks(engine, music_dir, downloads):
    progress = scan(engine, music_dir, (AREA,))
    assert len(paths(engine)) == LIBRARY
    assert not any(p.startswith(f"{AREA}/") for p in paths(engine))
    assert progress.total == LIBRARY and progress.left_for_area == 0


def test_an_unconfirmed_folder_is_still_library(engine, settings, music_dir, downloads, client):
    """RELEASOMAT_FOLDER alone changes nothing: only the owner's click keeps the folder out."""
    settings.releasomat_folder = AREA
    scan_job.start(settings)
    scan_job.wait()
    assert len(paths(engine)) == LIBRARY + len(DOWNLOADS)


def test_existing_rows_leave_once_with_their_marks(engine, music_dir, downloads):
    scan(engine, music_dir)
    ids = area_ids(engine)
    assert len(ids) == len(DOWNLOADS)
    with Session(engine) as session:
        library_copy = session.exec(select(Track.id).where(~Track.path.startswith(AREA))).first()
        session.add(PendingChange(track_id=ids[0], field="title", new_value="New"))
        session.add(FinalTrack(track_id=ids[1], mtime=0))
        session.add(SecretTrack(track_id=ids[1]))
        # A library copy queued for the trash in favour of a download: the decision goes.
        session.add(
            PendingChange(
                track_id=library_copy, field="trash", old_value="x", new_value=str(ids[0])
            )
        )
        session.add(PendingChange(track_id=library_copy, field="bpm", new_value="120"))
        session.commit()

    progress = scan(engine, music_dir, (AREA,))
    assert (progress.left_for_area, progress.removed) == (len(DOWNLOADS), 0)
    assert len(paths(engine)) == LIBRARY
    with Session(engine) as session:
        left = session.exec(select(PendingChange.track_id, PendingChange.field)).all()
        assert left == [(library_copy, "bpm")]  # the library copy's own change stays
        assert not session.exec(select(FinalTrack)).all()
        assert not session.exec(select(SecretTrack)).all()
    assert all(path.exists() for path in downloads.rglob("*.*"))  # the files stay

    again = scan(engine, music_dir, (AREA,))
    assert (again.left_for_area, again.removed) == (0, 0)


def test_files_vanishing_outside_the_area_still_count_as_removed(engine, music_dir, downloads):
    scan(engine, music_dir)
    (music_dir / "Unsorted" / "untagged.mp3").unlink()
    progress = scan(engine, music_dir, (AREA,))
    assert (progress.left_for_area, progress.removed) == (len(DOWNLOADS), 1)


def test_the_empty_library_guard_ignores_the_area(engine, music_dir, downloads):
    """An unmounted share stops the scan, even if the area's files are still there."""
    scan(engine, music_dir, (AREA,))
    for path in list(music_dir.rglob("*.*")):
        if AREA not in path.parts:
            path.unlink()
    with pytest.raises(EmptyLibraryError):
        scan(engine, music_dir, (AREA,))
    assert len(paths(engine)) == LIBRARY


def test_a_library_of_downloads_only_may_empty(engine, tmp_path):
    """No library tracks outside the area: keeping it out empties the lists, that's no error."""
    music = tmp_path / "only"
    (music / AREA).mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.mp3", music / AREA / "a.mp3")
    scan(engine, music)
    progress = scan(engine, music, (AREA,))
    assert progress.left_for_area == 1 and not paths(engine)


def test_a_nested_area_is_skipped_too(engine, music_dir):
    nested = music_dir / "Downloads" / AREA
    nested.mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.mp3", nested / "a.mp3")
    shutil.copy(FIXTURES / "tagged.mp3", music_dir / "Downloads" / "mine.mp3")
    scan(engine, music_dir, (f"Downloads/{AREA}",))
    assert "Downloads/mine.mp3" in paths(engine)
    assert f"Downloads/{AREA}/a.mp3" not in paths(engine)


# --- The guards -------------------------------------------------------------------------------


def test_the_area_is_no_genre_folder(music_dir, downloads):
    assert AREA in naming.existing_folders(music_dir)
    assert AREA not in naming.existing_folders(music_dir, (AREA,))


def test_an_import_never_lands_in_the_area(engine, settings, music_dir, downloads):
    set_prefs(engine, folder_layout="custom", folder_pattern="Releasomat/{artist}",
              releasomat_area=AREA)  # fmt: skip
    (settings.import_dir).mkdir()
    shutil.copy(FIXTURES / "tagged.mp3", settings.import_dir / "new.mp3")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        result = plan(session, session.exec(select(InboxTrack)).one(), music_dir)
    assert result.destination.startswith(f"{AREA}/")
    assert "it would land in the Releasomat folder: change the folder pattern" in result.problems


def test_no_genre_folder_is_proposed_in_the_area(engine, settings, music_dir, downloads):
    unsorted = music_dir / naming.UNSORTED
    unsorted.mkdir()
    shutil.copy(FIXTURES / "tagged.flac", unsorted / "song.flac")
    audio = FLAC(unsorted / "song.flac")
    audio["genre"] = AREA
    audio.save()
    scan(engine, music_dir, (AREA,))
    with Session(engine) as session:
        assert [p.folder for p in folders.proposals(session, music_dir)] == [AREA]
    set_prefs(engine, releasomat_area=AREA)
    with Session(engine) as session:
        assert folders.proposals(session, music_dir) == []


def test_apply_and_undo_never_write_into_the_area(engine, settings, music_dir, downloads):
    """Between the click and the scan, and for changes applied before the switch."""
    scan(engine, music_dir)
    track_id = area_ids(engine)[0]
    target = music_dir / AREA / DOWNLOADS[0]
    before = target.read_bytes()
    with Session(engine) as session:
        session.add(PendingChange(track_id=track_id, field="title", new_value="Changed"))
        changeset = ChangeSet(tracks=1, written=1, fields="Title")
        session.add(changeset)
        session.flush()
        session.add(
            ChangeEntry(
                changeset_id=changeset.id,
                track_id=track_id,
                path=f"{AREA}/{DOWNLOADS[0]}",
                changes=json.dumps({"title": ["Old", "New"]}),
                snapshot=json.dumps({}),
                mtime_after=target.stat().st_mtime,
            )
        )
        session.commit()
        changeset_id = changeset.id
    set_prefs(engine, releasomat_area=AREA)

    progress = WriteProgress()
    apply_pending(engine, music_dir, progress)
    assert progress.failed == 1 and "in the Releasomat folder" in progress.errors[0]
    undone = WriteProgress()
    undo_changeset(engine, music_dir, changeset_id, undone, settings=settings)
    assert undone.failed == 1 and "Releasomat folder" in undone.errors[0]
    assert target.read_bytes() == before
    with Session(engine) as session:  # still pending: it goes with the row on the next scan
        assert session.exec(select(PendingChange)).one().new_value == "Changed"


def test_a_trashed_copy_restored_into_the_area_isnt_read_in(engine, music_dir, downloads):
    from app import trash

    entry = trash.delete(music_dir, f"{AREA}/{DOWNLOADS[0]}")
    set_prefs(engine, releasomat_area=AREA)
    with Session(engine) as session:
        assert restore_copy(session, music_dir, entry) == f"{AREA}/{DOWNLOADS[0]}"
    assert (downloads / DOWNLOADS[0]).exists()
    assert f"{AREA}/{DOWNLOADS[0]}" not in paths(engine)


# --- Settings → Releasomat --------------------------------------------------------------------


def test_without_releasomat_settings_say_nothing_about_it(client):
    page = client.get("/settings").text
    assert "Releasomat" not in page


def test_settings_show_what_leaves_before_the_click(client, settings, engine, music_dir,
                                                    downloads, monkeypatch):  # fmt: skip
    monkeypatch.setenv("RELEASOMAT_FOLDER", AREA)
    get_settings.cache_clear()
    scan(engine, music_dir)
    ids = area_ids(engine)
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids[0], mtime=0))
        session.add(DuplicateTrack(track_id=ids[1], group_id=1, reason="name"))
        session.commit()

    page = client.get("/settings").text
    assert 'id="releasomat"' in page and "not kept out yet" in page
    assert "<strong>3 tracks</strong> out of Tagwerk" in page
    assert "1 final mark: removed with the tracks" in page
    assert "1 duplicate group with a copy there" in page
    assert "Keep this folder out of the library" in page
    shown = client.get("/api/releasomat/area").json()
    assert shown["folder"] == AREA and shown["precheck"]["tracks"] == 3

    answer = client.post("/settings/releasomat/keep-out", data={"folder": AREA})
    assert answer.status_code == 200 and "kept out of the library" in answer.text
    scan_job.wait()
    assert prefs(engine).releasomat_area == AREA
    assert len(paths(engine)) == LIBRARY
    with Session(engine) as session:
        note = session.exec(select(Notification)).one()
    assert note.topic == "releasomat" and note.summary.startswith("3 tracks left the library")
    page = client.get("/settings").text
    assert "Treat it as library again" in page and "folder kept out" in page

    client.post("/settings/releasomat/library")
    scan_job.wait()
    assert prefs(engine).releasomat_area == ""
    assert len(paths(engine)) == LIBRARY + len(DOWNLOADS)


def test_only_the_folder_shown_can_be_confirmed(client, engine, music_dir, downloads,
                                                monkeypatch):  # fmt: skip
    monkeypatch.setenv("RELEASOMAT_FOLDER", AREA)
    get_settings.cache_clear()
    (music_dir / "Other").mkdir()
    answer = client.post("/settings/releasomat/keep-out", data={"folder": "Other"})
    assert answer.status_code == 422 and "changed meanwhile" in answer.text
    assert client.post("/api/releasomat/area", json={"folder": "Fixture Artist"}).status_code == 409
    assert prefs(engine).releasomat_area == ""


def test_a_folder_that_fails_its_check_is_explained(client, monkeypatch):
    monkeypatch.setenv("RELEASOMAT_FOLDER", "Missing")
    get_settings.cache_clear()
    page = client.get("/settings").text
    assert "check the folder" in page and "There is no folder Missing" in page
    assert "Keep this folder out of the library" not in page


def test_the_releasomat_topic_is_shown_only_when_set_up(client, engine, monkeypatch):
    assert "Tracks that left the library" not in client.get("/settings").text
    client.post("/settings/notifications", data={"topics": ["scan"]})  # saved while hidden
    assert prefs(engine).notifications["releasomat"] is True
    monkeypatch.setenv("RELEASOMAT_FOLDER", AREA)
    get_settings.cache_clear()
    assert "Tracks that left the library" in client.get("/settings").text
    client.post("/settings/notifications", data={"topics": ["scan"]})
    assert prefs(engine).notifications["releasomat"] is False

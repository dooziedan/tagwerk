"""Removing a program's private ID3 data (PRIV frames, e.g. Traktor's) through Changes."""

import os
import shutil

import mutagen
import pytest
from mutagen.id3 import PRIV
from sqlmodel import Session, select

from app import changes, writer
from app.changes import WriteProgress
from app.images import ImageStore
from app.models import ChangeEntry, FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"
TRAKTOR = os.urandom(30_000)  # like Traktor's waveform and beat grid


def add_private(path):
    audio = mutagen.File(path)  # WAV and AIFF keep their ID3 tags in a chunk
    audio.tags.add(PRIV(owner="TRAKTOR4", data=TRAKTOR))
    audio.tags.add(PRIV(owner="www.amazon.com", data=b"\x01" * 20))
    audio.save()


def tags(path):
    return mutagen.File(path).tags


def private(path) -> dict[str, bytes]:
    return {f.owner: f.data for f in tags(path).getall("PRIV")}


@pytest.mark.parametrize("fmt", ["mp3", "wav", "aiff"])
def test_removing_private_data_and_undo_restore_it_exactly(tmp_path, fmt):
    path = tmp_path / f"t.{fmt}"
    shutil.copy(FIXTURES / f"tagged.{fmt}", path)
    add_private(path)
    images = ImageStore(tmp_path / "images")
    title_before = tags(path).getall("TIT2")[0].text

    snapshot = writer.write(path, {"private:TRAKTOR4": None}, images)
    assert private(path) == {"www.amazon.com": b"\x01" * 20}  # only Traktor's data is gone
    assert tags(path).getall("TIT2")[0].text == title_before

    writer.undo(path, snapshot, images)
    assert private(path)["TRAKTOR4"] == TRAKTOR


def test_private_data_only_exists_in_id3(tmp_path):
    path = tmp_path / "t.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    with pytest.raises(writer.WriteError):
        writer.write(path, {"private:TRAKTOR4": None})


def test_label():
    assert writer.label("private:TRAKTOR4") == "Private data (TRAKTOR4)"
    assert writer.label("cover") == "Cover art"


@pytest.fixture
def library(engine, music_dir):
    for name in ("tagged.mp3", "tagged.wav"):
        add_private(music_dir / ALBUM / name)
    scan_library(engine, music_dir, ScanProgress())
    return music_dir


def ids(engine) -> dict[str, int]:
    with Session(engine) as session:
        return {t.path.rsplit("/", 1)[-1]: t.id for t in session.exec(select(Track))}


def test_staging_finds_every_file_with_the_data_and_skips_final_tracks(engine, library, settings):
    track = ids(engine)
    with Session(engine) as session:
        wav = session.get(Track, track["tagged.wav"])
        session.add(FinalTrack(track_id=wav.id, mtime=wav.mtime))  # final: locked
        session.commit()
        assert changes.stage_private_removal(session, "TRAKTOR4") == 1
        assert changes.stage_private_removal(session, "TRAKTOR4") == 0  # already pending
        rows = session.exec(select(PendingChange)).all()
        assert [(r.track_id, r.field, r.new_value, r.source) for r in rows] == [
            (track["tagged.mp3"], "private:TRAKTOR4", None, "private-data")
        ]


def test_apply_and_undo_through_changes(engine, library, settings):
    images = ImageStore(settings.config_dir / "images")
    with Session(engine) as session:
        changes.stage_private_removal(session, "TRAKTOR4")
    progress = WriteProgress()
    changes.apply_pending(engine, library, progress, images)
    assert (progress.written, progress.failed) == (2, 0)
    with Session(engine) as session:
        entries = session.exec(select(ChangeEntry)).all()
        assert all(e.error is None for e in entries)  # read back: the data is gone
    for name in ("tagged.mp3", "tagged.wav"):
        assert "TRAKTOR4" not in private(library / ALBUM / name)

    undo = WriteProgress(action="undo")
    changes.undo_changeset(engine, library, entries[0].changeset_id, undo, images)
    for name in ("tagged.mp3", "tagged.wav"):
        assert private(library / ALBUM / name)["TRAKTOR4"] == TRAKTOR


def test_field_page_offers_removal_and_changes_page_names_it(client, engine, library):
    page = client.get("/fields/detail", params={"system": "id3", "name": "PRIV:TRAKTOR4"}).text
    assert "Private data of TRAKTOR4" in page and 'action="/fields/private/remove"' in page
    assert (
        "/fields/private/remove"
        not in client.get("/fields/detail", params={"system": "id3", "name": "TIT2"}).text
    )
    response = client.post("/fields/private/remove", data={"owner": "TRAKTOR4"})
    assert response.status_code == 200 and "Private data (TRAKTOR4)" in response.text


def test_tag_fields_page_points_out_traktor_data(client, engine, library):
    page = client.get("/fields").text
    assert "Traktor data in 2 files" in page
    assert "PRIV%3ATRAKTOR4" in page


@pytest.fixture
def inbox_with_traktor(settings, engine):
    from app.inbox import scan_inbox

    settings.import_dir.mkdir(parents=True)
    path = settings.import_dir / "Artist - Title.mp3"
    shutil.copy(FIXTURES / "tagged.mp3", path)
    add_private(path)
    scan_inbox(engine, settings.import_dir, ScanProgress())
    return path


def set_remove_traktor(engine, on: bool):
    from dataclasses import replace

    from app import preferences

    with Session(engine) as session:
        prefs = preferences.load(session)
        preferences.save(session, replace(prefs, remove_traktor_on_import=on))


def test_import_removes_traktor_data_when_switched_on_and_undo_restores_it(
    engine, settings, inbox_with_traktor
):
    from app.importer import import_tracks
    from app.models import ChangeSet, InboxTrack

    set_remove_traktor(engine, True)
    images = ImageStore(settings.config_dir / "images")
    with Session(engine) as session:
        tid = session.exec(select(InboxTrack)).one().id
    progress = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, [tid], progress, images)
    assert progress.written == 1, progress.errors
    with Session(engine) as session:
        track = session.exec(select(Track).where(Track.path.endswith("Artist - Title.mp3"))).one()
        imported = settings.music_dir / track.path
        changeset = session.exec(select(ChangeSet)).one()
    assert set(private(imported)) == {"www.amazon.com"}  # only Traktor's data is gone
    assert "Private data (TRAKTOR4)" in changeset.fields

    undo = WriteProgress(action="undo")
    changes.undo_changeset(
        engine, settings.music_dir, changeset.id, undo, images, settings.import_dir, settings
    )
    assert private(inbox_with_traktor)["TRAKTOR4"] == TRAKTOR


def test_import_keeps_traktor_data_by_default(engine, settings, inbox_with_traktor):
    from app.importer import plan
    from app.models import InboxTrack

    with Session(engine) as session:
        track = session.exec(select(InboxTrack)).one()
        assert writer.TRAKTOR not in plan(session, track, settings.music_dir).changes
    set_remove_traktor(engine, True)
    with Session(engine) as session:
        track = session.exec(select(InboxTrack)).one()
        assert plan(session, track, settings.music_dir).changes[writer.TRAKTOR] is None


def test_setting_is_saved_from_settings(client, engine):
    from app import preferences

    client.post("/settings/choices/import", data={"automation": "ask", "folder_layout": "genre",
                                                  "remove_traktor_on_import": "on"})  # fmt: skip
    with Session(engine) as session:
        assert preferences.load(session).remove_traktor_on_import is True
    assert 'name="remove_traktor_on_import" role="switch" checked' in client.get("/settings").text

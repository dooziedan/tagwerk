import re
import shutil

import pytest
from sqlmodel import Session, select

from app.changes import WriteProgress, undo_changeset
from app.importer import folder_for, import_tracks
from app.inbox import save_values, scan_inbox
from app.models import ChangeSet, InboxTrack, Track
from app.scanner import ScanProgress
from app.tags import read_file
from tests.conftest import FIXTURES

NAME = "Fisher - Losing It (Extended Mix).mp3"


@pytest.fixture
def inbox(settings, engine):
    root = settings.import_dir
    (root / "Pool").mkdir(parents=True)
    shutil.copy(FIXTURES / "untagged.mp3", root / "Pool" / NAME)
    shutil.copy(FIXTURES / "untagged.mp3", root / "promo.mp3")  # no artist anywhere
    scan_inbox(engine, root, ScanProgress())
    return root


def ids(engine, *paths):
    with Session(engine) as session:
        rows = session.exec(select(InboxTrack)).all()
        return [t.id for t in rows if t.path in paths]


def run_import(engine, settings, track_ids) -> WriteProgress:
    progress = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, track_ids, progress)
    return progress


def test_import_writes_tags_and_moves_the_file_unrenamed(engine, settings, inbox):
    track_id = ids(engine, f"Pool/{NAME}")[0]
    with Session(engine) as session:  # the owner adds a genre on the review page
        save_values(session, session.get(InboxTrack, track_id), {"genre": "Liquid"})

    progress = run_import(engine, settings, [track_id])
    assert (progress.written, progress.failed) == (1, 0)

    target = settings.music_dir / "Drum & Bass" / NAME  # genre folder, same filename
    assert target.exists() and not (inbox / "Pool" / NAME).exists()
    info = read_file(target)
    assert (info.artist, info.title) == ("Fisher", "Losing It (Extended Mix)")
    assert info.genre == "Liquid"  # what the owner typed; the folder still uses the main genre
    with Session(engine) as session:
        assert session.exec(select(Track).where(Track.path == f"Drum & Bass/{NAME}")).one()
        assert session.get(InboxTrack, track_id) is None
        assert session.exec(select(ChangeSet)).one().kind == "import"


def test_tracks_without_artist_stay_in_the_inbox(engine, settings, inbox):
    progress = run_import(engine, settings, ids(engine, "promo.mp3"))
    assert progress.failed == 1 and "needs artist" in progress.errors[0]
    assert (inbox / "promo.mp3").exists()


def test_existing_files_are_never_overwritten_or_renamed(engine, settings, inbox):
    existing = settings.music_dir / "_Unsorted" / NAME
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"already here")
    before = (inbox / "Pool" / NAME).read_bytes()

    progress = run_import(engine, settings, ids(engine, f"Pool/{NAME}"))
    assert progress.failed == 1 and "already exists" in progress.errors[0]
    assert existing.read_bytes() == b"already here"
    assert (inbox / "Pool" / NAME).read_bytes() == before  # tags weren't written either
    assert sorted(p.name for p in existing.parent.iterdir()) == [NAME]  # no "(2)" copies


def test_undo_moves_the_file_back_with_its_old_tags(engine, settings, inbox):
    before = (inbox / "Pool" / NAME).read_bytes()
    run_import(engine, settings, ids(engine, f"Pool/{NAME}"))
    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id

    progress = WriteProgress(action="undo")
    undo_changeset(
        engine, settings.music_dir, changeset_id, progress, import_dir=settings.import_dir
    )
    assert (progress.written, progress.failed) == (1, 0)
    assert (inbox / "Pool" / NAME).read_bytes() == before
    assert not (settings.music_dir / "_Unsorted" / NAME).exists()
    with Session(engine) as session:
        assert not session.exec(select(Track).where(Track.path.contains("Losing It"))).all()


def test_folder_for_genre():
    assert folder_for("Drum & Bass; Liquid") == "Drum & Bass"
    assert folder_for("Deep House") == "House"
    assert folder_for("dnb") == "Drum & Bass"
    assert folder_for(None) == "_Unsorted"
    assert folder_for("AC/DC Rock") == "AC-DC Rock"  # no folder separators in names


def test_import_from_the_inbox_page(client, settings, inbox):
    from app.jobs import write_job

    track_id = client.get("/api/inbox").json()[0]["id"]
    page = client.get(f"/inbox/{track_id}").text
    assert "On import goes to" in page
    client.post("/inbox/import", data={"ids": [str(i) for i in [track_id]]})
    write_job.wait(30)
    assert "Imported" in client.get("/inbox").text


def test_cover_chosen_on_the_review_page_is_written_on_import(client, engine, settings):
    from app.covers import find_cover
    from app.jobs import inbox_job, write_job
    from tests.test_writer import PNG

    (settings.import_dir / "Pool").mkdir(parents=True)
    source = settings.import_dir / "Pool" / NAME
    shutil.copy(FIXTURES / "tagged.mp3", source)
    old_cover = find_cover(source)
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    track_id = client.get("/api/inbox").json()[0]["id"]

    client.post(
        f"/inbox/{track_id}",
        data={"cover_action": "replace", "then": "list"},
        files={"cover_file": ("cover.png", PNG, "image/png")},
    )
    page = client.get(f"/inbox/{track_id}").text
    assert "New cover, written on import" in page and "your choice" in page
    assert find_cover(source) == old_cover  # nothing written before import

    client.post("/inbox/import", data={"ids": [str(track_id)]})
    write_job.wait(30)
    target = settings.music_dir / "_Unsorted" / NAME
    if not target.exists():  # the fixture has a genre: find the folder it went to
        target = next(settings.music_dir.rglob(NAME))
    assert find_cover(target) == (PNG, "image/png")

    changeset = client.get("/api/changesets").json()[0]["id"]
    client.post(f"/changes/history/{changeset}/undo")
    write_job.wait(30)
    assert find_cover(source) == old_cover  # back in the inbox with its old cover


def test_cover_can_be_removed_on_import(engine, settings):
    from app.inbox import set_cover

    (settings.import_dir).mkdir(parents=True)
    shutil.copy(FIXTURES / "tagged.flac", settings.import_dir / NAME.replace(".mp3", ".flac"))
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        track = session.exec(select(InboxTrack)).one()
        set_cover(session, track, None)
        track_id = track.id
    run_import(engine, settings, [track_id])
    imported = next(settings.music_dir.rglob("*.flac"))
    assert not read_file(imported).has_cover


def test_the_inbox_check_doesnt_grey_out_the_import_button(client, inbox, monkeypatch):
    """Opening the inbox starts a quick check of the folder; Import must stay usable."""
    from app.jobs import inbox_job

    monkeypatch.setattr(inbox_job, "status", "running")  # as right after opening the page
    page = client.get("/inbox").text
    button = re.search(r'<button type="submit" form="inbox-import"[^>]*>', page).group(0)
    assert "disabled" not in button

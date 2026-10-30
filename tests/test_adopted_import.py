"""Tracks adopted from Releasomat stay the same song in Navidrome (ADR 0046): the import moves the
file first with the tags it has, waits for Navidrome to list it, then writes the new tags."""

import json
import shutil

import pytest
from sqlmodel import Session, select

from app import navidrome, writer
from app.changes import WriteProgress
from app.importer import import_tracks
from app.inbox import owner_values, save_values, scan_inbox
from app.models import ChangeEntry, InboxTrack, ReleasomatAdoption
from app.scanner import ScanProgress
from app.tags import read_file
from app.undo import undo_changeset
from tests.conftest import FIXTURES
from tests.fake_navidrome import URL, ScanningNavidrome

PROMO = "A/Someone - Promo.mp3"  # in Releasomat's folder, relative to it
LATER = "B/Other - Later.mp3"


def download(music_dir, rel: str, title: str, album: str) -> None:
    """A Releasomat download in its folder inside the library, with Releasomat's tags."""
    path = music_dir / "Releasomat" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "tagged.mp3", path)
    writer.write(path, {"title": title, "album": album, "artist": "Someone"})


def adopt(engine, settings, fake, *rels: str) -> None:
    """What Adopt does: the files move into /import/Releasomat/…, Navidrome notices they are
    gone (their songs are missing now), and the adoptions are recorded."""
    for rel in rels:
        target = settings.import_dir / "Releasomat" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(settings.music_dir / "Releasomat" / rel, target)
    fake.scan()
    with Session(engine) as session:
        for rel in rels:
            size = (settings.import_dir / "Releasomat" / rel).stat().st_size
            session.add(ReleasomatAdoption(area_path=rel, inbox_path=f"Releasomat/{rel}",
                                           size=size))  # fmt: skip
        session.commit()
    scan_inbox(engine, settings.import_dir, ScanProgress())


def inbox_id(engine, rel: str) -> int:
    with Session(engine) as session:
        return session.exec(select(InboxTrack.id).where(InboxTrack.path == rel)).one()


def improve(engine, rel: str, **values) -> int:
    """The owner changes tags on the track's review page (staged until the import)."""
    with Session(engine) as session:
        track = session.exec(select(InboxTrack).where(InboxTrack.path == rel)).one()
        assert save_values(session, track, values) == {}
        return track.id


def run_import(engine, settings, ids) -> WriteProgress:
    progress = WriteProgress(action="import")
    import_tracks(engine, settings.import_dir, settings.music_dir, ids, progress, None, settings)
    return progress


def entries(engine) -> list[ChangeEntry]:
    with Session(engine) as session:
        return list(session.exec(select(ChangeEntry).order_by(ChangeEntry.id)))


@pytest.fixture
def fake(settings, monkeypatch):
    """Navidrome set up, scanning the music folder; one download in a Releasomat playlist."""
    settings.import_dir.mkdir()
    fake = ScanningNavidrome(settings.music_dir)
    monkeypatch.setattr(navidrome.urllib.request, "urlopen", fake)
    monkeypatch.setattr(navidrome, "SCAN_POLL", 0)
    monkeypatch.setattr(navidrome, "SCAN_WAIT", 5)  # a scan that never ends fails, not hangs
    monkeypatch.setattr(settings, "navidrome_url", URL)
    monkeypatch.setattr(settings, "navidrome_user", "admin")
    monkeypatch.setattr(settings, "navidrome_password", "secret")
    download(settings.music_dir, PROMO, "Promo", "Promo Album")
    fake.scan()
    return fake


def test_an_adopted_track_moves_first_and_stays_the_same_song(client, engine, settings, fake):
    [(song_id, _)] = [(i, s) for i, s in fake.songs.items() if s["title"] == "Promo"]
    adopt(engine, settings, fake, PROMO)
    assert fake.songs[song_id]["missing"]  # waiting in the inbox: Navidrome hides it
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)",
                       album="Promo EP")  # fmt: skip
    fake.calls.clear()

    progress = run_import(engine, settings, [track_id])
    assert (progress.written, progress.failed) == (1, 0)
    [entry] = entries(engine)
    # Navidrome scanned the file at its library place while it still had Releasomat's tags...
    assert fake.scans[-1][entry.path] == ("Promo", "Promo Album")
    assert fake.calls[:3] == ["getScanStatus", "startScan", "getScanStatus"]
    assert "search3" in fake.calls
    # ...and only then were the new tags written.
    info = read_file(settings.music_dir / entry.path)
    assert (info.title, info.album) == ("Promo (Extended Mix)", "Promo EP")
    assert json.loads(entry.details) == {"navidrome": "listed"}
    assert entry.snapshot and entry.moved_from == f"Releasomat/{PROMO}"

    navidrome.rescan_after_write(settings, progress.written)  # what the import job does next
    fake.scan()
    assert fake.song_at(entry.path)[0] == song_id  # the same song, with the new tags
    assert fake.songs[song_id]["title"] == "Promo (Extended Mix)"
    assert not [s for s in fake.songs.values() if s["missing"]]  # nothing left behind

    page = client.get(f"/changes/history/{entry.changeset_id}").text
    assert "Adopted from Releasomat" in page and "keeps it as the same song" in page


def test_in_one_step_navidrome_would_make_a_new_song(engine, settings, fake, monkeypatch):
    """Why the two steps: without Navidrome set up the import works as before (tags first,
    then the move), and Navidrome sees a new song; the old one stays missing."""
    [song_id] = [i for i, s in fake.songs.items() if s["title"] == "Promo"]
    adopt(engine, settings, fake, PROMO)
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)")
    monkeypatch.setattr(settings, "navidrome_url", "")
    fake.calls.clear()

    progress = run_import(engine, settings, [track_id])
    assert progress.written == 1 and fake.calls == []  # nothing asked
    [entry] = entries(engine)
    assert entry.details is None
    fake.scan()
    assert fake.song_at(entry.path)[0] != song_id
    assert fake.songs[song_id]["missing"]


def test_one_scan_for_all_adopted_tracks_and_other_tracks_as_before(engine, settings, fake):
    download(settings.music_dir, LATER, "Later", "Later Album")
    fake.scan()
    before = {s["title"]: i for i, s in fake.songs.items()}
    adopt(engine, settings, fake, PROMO, LATER)
    (settings.import_dir / "Pool").mkdir()
    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / "Pool" / "Fisher - Losing It.mp3")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    ids = [improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)"),
           improve(engine, f"Releasomat/{LATER}", title="Later (Club Mix)"),
           inbox_id(engine, "Pool/Fisher - Losing It.mp3")]  # fmt: skip
    fake.calls.clear()

    progress = run_import(engine, settings, ids)
    assert (progress.written, progress.failed) == (3, 0)
    assert fake.calls.count("startScan") == 1
    by_from = {e.moved_from: e for e in entries(engine)}
    pool = by_from["Pool/Fisher - Losing It.mp3"]
    assert pool.details is None  # not adopted: tags first, then the move, as always
    assert fake.scans[-1][pool.path] == ("Losing It", None)  # it had its new tags already
    fake.scan()
    for rel, title in ((PROMO, "Promo"), (LATER, "Later")):
        entry = by_from[f"Releasomat/{rel}"]
        assert json.loads(entry.details) == {"navidrome": "listed"}
        assert fake.song_at(entry.path)[0] == before[title]


def test_navidrome_not_answering_doesnt_stop_the_import(engine, settings, fake):
    adopt(engine, settings, fake, PROMO)
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)")
    fake.down = True

    progress = run_import(engine, settings, [track_id])
    assert (progress.written, progress.failed) == (1, 0)
    [entry] = entries(engine)
    assert read_file(settings.music_dir / entry.path).title == "Promo (Extended Mix)"
    note = json.loads(entry.details)
    assert note["navidrome"] == "unconfirmed" and "Can't reach Navidrome" in note["why"]


def test_a_broken_answer_from_navidrome_doesnt_stop_the_import(engine, settings, fake,
                                                                monkeypatch):  # fmt: skip
    """An answer cut off mid-way raises http.client errors, not OSError: still no stop."""
    import http.client

    adopt(engine, settings, fake, PROMO)
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)")

    def cut_off(url, timeout):
        raise http.client.IncompleteRead(b"{")

    monkeypatch.setattr(navidrome.urllib.request, "urlopen", cut_off)
    progress = run_import(engine, settings, [track_id])
    assert (progress.written, progress.failed) == (1, 0)
    [entry] = entries(engine)
    assert read_file(settings.music_dir / entry.path).title == "Promo (Extended Mix)"
    assert json.loads(entry.details)["navidrome"] == "unconfirmed"


def test_files_without_tags_to_write_import_in_one_step(engine, settings, fake):
    adopt(engine, settings, fake, PROMO)
    fake.calls.clear()
    progress = run_import(engine, settings, [inbox_id(engine, f"Releasomat/{PROMO}")])
    assert progress.written == 1 and fake.calls == []  # nothing changes: nothing to wait for


def test_if_the_tags_cant_be_written_the_file_goes_back_to_the_inbox(
    engine, settings, fake, monkeypatch
):
    adopt(engine, settings, fake, PROMO)
    inbox_file = settings.import_dir / "Releasomat" / PROMO
    before = inbox_file.read_bytes()
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)")

    def broken(path, changes, images=None):
        raise writer.WriteError("the disk is full")

    monkeypatch.setattr(writer, "write", broken)
    progress = run_import(engine, settings, [track_id])
    assert progress.failed == 1 and "the disk is full" in progress.errors[0]
    assert inbox_file.read_bytes() == before
    assert not list(settings.music_dir.rglob("Someone - Promo.mp3"))
    with Session(engine) as session:  # still in the inbox list, with the owner's title
        assert owner_values(session, track_id) == {"title": "Promo (Extended Mix)"}
    [entry] = entries(engine)
    assert entry.error and entry.moved_from is None


def test_undo_moves_it_back_with_releasomats_tags(engine, settings, fake):
    adopt(engine, settings, fake, PROMO)
    track_id = improve(engine, f"Releasomat/{PROMO}", title="Promo (Extended Mix)",
                       album="Promo EP")  # fmt: skip
    progress = run_import(engine, settings, [track_id])

    undone = WriteProgress(action="undo")
    undo_changeset(engine, settings.music_dir, progress.changeset_id, undone,
                   import_dir=settings.import_dir, settings=settings)  # fmt: skip
    assert (undone.written, undone.failed) == (1, 0)
    info = read_file(settings.import_dir / "Releasomat" / PROMO)
    assert (info.title, info.album) == ("Promo", "Promo Album")
    assert not list(settings.music_dir.rglob("Someone - Promo.mp3"))

"""Better copies: an inbox file that sounds better replaces its library copy (ADR 0037)."""

import os
import shutil
import time
from types import SimpleNamespace

import pytest
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from sqlmodel import Session, select

from app import analysis, preferences, trash, upgrade
from app.changes import WriteProgress, stage
from app.duplicates import sound
from app.images import ImageStore
from app.inbox import save_values, scan_inbox
from app.models import ChangeSet, FinalTrack, InboxTrack, LibraryLoudness, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file
from app.undo import undo_changeset
from tests.conftest import FIXTURES

ALBUM = "Fixture Artist/Fixture Album"
MP3 = f"{ALBUM}/tagged.mp3"
FLAC_PATH = f"{ALBUM}/tagged.flac"  # where the better copy goes: same name, its extension


def audio(fmt, bitrate=None, sample_rate=44100, bits=None):
    return SimpleNamespace(format=fmt, bitrate=bitrate, sample_rate=sample_rate,
                           bits_per_sample=bits)  # fmt: skip


@pytest.mark.parametrize(
    ("new", "old", "why"),
    [
        (audio("flac", bits=16), audio("mp3", 320_000), "lossless instead of lossy"),
        (audio("aiff", bits=24), audio("wav", bits=16), "a higher resolution"),
        (audio("flac", bits=16, sample_rate=96000), audio("flac", bits=16), "a higher resolution"),
        (audio("mp3", 320_000), audio("mp3", 192_000), "a higher bitrate"),
        (audio("mp3", 320_000), audio("m4a", 256_000), "a higher bitrate"),
        (audio("mp3", 320_000), audio("mp3", 300_000), None),  # a VBR file: about the same
        (audio("mp3", 320_000), audio("flac", bits=16), None),  # never lossy over lossless
        (audio("flac", bits=16), audio("wav", bits=16), None),  # the same sound
        (audio("flac", bits=24, sample_rate=44100), audio("wav", 0, 48000, 16), None),  # mixed
        (audio("flac", bits=None), audio("wav", bits=16), None),  # unknown: no guessing
    ],
)
def test_only_a_clearly_better_sound_counts(new, old, why):
    assert upgrade.better(new, old) == why


def test_aac_in_m4a_is_lossy_on_the_duplicates_page_too():
    # AAC files report 16 bit as well; they used to rank as lossless above a 320 kbps MP3.
    aac = audio("m4a", 128_000, bits=16)
    assert sound(aac) < sound(audio("mp3", 320_000)) < sound(audio("flac", bits=16))


@pytest.fixture
def library(engine, settings):
    """A library with one MP3 of "Silent Track" (32 kbps): BPM, key, cover, IDs, no comment."""
    for path in (settings.music_dir / ALBUM).iterdir():
        if path.name != "tagged.mp3":
            path.unlink()
    shutil.rmtree(settings.music_dir / "Info Artist")
    tags = ID3(settings.music_dir / MP3)
    tags.delall("COMM")  # no comment: the inbox file's fills the gap
    tags.save()
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        return session.exec(select(Track).where(Track.path == MP3)).one().id


@pytest.fixture
def inbox(settings, engine, library):
    """The same track as FLAC in the inbox, with poorer tags (no BPM) and a comment."""
    root = settings.import_dir
    (root / "Pool").mkdir(parents=True)
    path = root / "Pool" / "silent-track.flac"
    shutil.copy(FIXTURES / "tagged.flac", path)
    tags = FLAC(path)
    tags.pop("bpm", None)
    tags["comment"] = "from the pool"
    tags.save()
    old = time.time() - 600  # downloaded a while ago: not a half download
    os.utime(path, (old, old))
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        return session.exec(select(InboxTrack)).one().id


def found(engine, settings) -> list[upgrade.Upgrade]:
    with Session(engine) as session:
        return upgrade.upgrades(session, settings)


def replace(engine, settings, ids, tmp_path) -> WriteProgress:
    progress = WriteProgress(action="upgrade")
    upgrade.replace(engine, settings, ids, progress, ImageStore(tmp_path / "images"))
    return progress


def test_a_lossless_copy_is_found_and_says_what_it_does(engine, settings, inbox, library):
    (better,) = found(engine, settings)
    assert (better.inbox.id, better.library.id) == (inbox, library)
    assert better.reason == "lossless instead of lossy"
    assert better.destination == FLAC_PATH
    assert (better.old_quality, better.new_quality) == ("MP3 · 32 kbps", "FLAC · 8 kHz · 16 bit")
    with Session(engine) as session:
        item = upgrade.plan(session, better, settings)
    assert item.changes["bpm"] == "126"  # the library copy's tags win
    assert "comment" not in item.changes  # the library copy has none: the inbox's stays
    assert not item.problems


def test_replacing_keeps_the_track_and_trashes_the_old_file(
    engine, settings, inbox, library, tmp_path
):
    with Session(engine) as session:
        old = session.get(Track, library)
        session.add(FinalTrack(track_id=library, mtime=old.mtime))
        session.add(LibraryLoudness(track_id=library, lufs=-9.0))
        session.commit()

    progress = replace(engine, settings, [inbox], tmp_path)
    assert (progress.written, progress.failed) == (1, 0), progress.errors

    music = settings.music_dir
    assert (music / FLAC_PATH).exists() and not (music / MP3).exists()
    assert not list(settings.import_dir.rglob("*.flac"))  # gone from the inbox
    assert [d.path for d in trash.items(music)] == [MP3]  # the old file waits in the trash
    info = read_file(music / FLAC_PATH)
    assert (info.bpm, info.key, info.comment) == (126.0, "Am", "from the pool")
    with Session(engine) as session:
        track = session.get(Track, library)  # the same row: history, added date, marks stay
        assert (track.path, track.format) == (FLAC_PATH, "flac")
        assert session.get(FinalTrack, library).mtime == track.mtime  # still final
        assert session.get(LibraryLoudness, library) is None  # measured again for the new file
        assert session.get(InboxTrack, inbox) is None
        assert session.exec(select(ChangeSet)).one().kind == "upgrade"


def test_undo_brings_both_files_back(engine, settings, inbox, library, tmp_path):
    inbox_file = settings.import_dir / "Pool" / "silent-track.flac"
    before = inbox_file.read_bytes()
    mp3 = (settings.music_dir / MP3).read_bytes()
    replace(engine, settings, [inbox], tmp_path)
    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id

    progress = WriteProgress(action="undo")
    undo_changeset(engine, settings.music_dir, changeset_id, progress,
                   ImageStore(tmp_path / "images"), settings.import_dir, settings)  # fmt: skip
    assert (progress.written, progress.failed) == (1, 0), progress.errors
    assert inbox_file.read_bytes() == before  # back in the inbox with its own tags
    assert (settings.music_dir / MP3).read_bytes() == mp3
    assert not (settings.music_dir / FLAC_PATH).exists()
    assert trash.items(settings.music_dir) == []
    with Session(engine) as session:
        assert session.get(Track, library).path == MP3


def test_undo_waits_when_the_trash_was_emptied(engine, settings, inbox, library, tmp_path):
    replace(engine, settings, [inbox], tmp_path)
    trash.empty(settings.music_dir)
    with Session(engine) as session:
        changeset_id = session.exec(select(ChangeSet)).one().id
    flac = (settings.music_dir / FLAC_PATH).read_bytes()

    progress = WriteProgress(action="undo")
    undo_changeset(engine, settings.music_dir, changeset_id, progress,
                   ImageStore(tmp_path / "images"), settings.import_dir, settings)  # fmt: skip
    assert progress.failed == 1 and "no longer in the library trash" in progress.errors[0]
    assert (settings.music_dir / FLAC_PATH).read_bytes() == flac  # nothing was touched


def test_no_better_copy_when_it_sounds_the_same_or_worse(engine, settings, library):
    root = settings.import_dir
    root.mkdir()
    shutil.copy(settings.music_dir / MP3, root / "same-file.mp3")  # the identical file
    shutil.copy(FIXTURES / "tagged.ogg", root / "worse.ogg")  # lossy, a lower bitrate
    scan_inbox(engine, root, ScanProgress())
    assert found(engine, settings) == []


def test_pending_changes_on_the_library_copy_block_it(engine, settings, inbox, library, tmp_path):
    with Session(engine) as session:
        stage(session, [library], {"comment": "not written yet"})
        (better,) = upgrade.upgrades(session, settings)
        assert upgrade.plan(session, better, settings).problems
    progress = replace(engine, settings, [inbox], tmp_path)
    assert progress.failed == 1 and "pending changes" in progress.errors[0]
    assert (settings.music_dir / MP3).exists()


def test_the_inbox_page_offers_to_replace(client, engine, settings, inbox, library):
    from app.jobs import write_job

    listing = client.get("/inbox").text
    assert "Better sound" in listing
    page = client.get(f"/inbox/{inbox}").text
    assert "Sounds better than your library copy" in page and "Replace library copy" in page
    assert client.get("/api/inbox").json()[0]["better_copy"]["destination"] == FLAC_PATH

    client.post(f"/inbox/{inbox}/upgrade", data={"show": "better"})
    write_job.wait(30)
    assert (settings.music_dir / FLAC_PATH).exists()
    history = client.get("/changes/history/1").text
    assert "Replaced with a better copy" in history and "tagged.mp3" in history


def test_automatic_replacing_only_when_switched_on(engine, settings, inbox, library):
    from app.jobs import inbox_job

    inbox_job.start(settings)
    inbox_job.wait(30)
    assert (settings.music_dir / MP3).exists()  # off by default: the owner presses Replace

    with Session(engine) as session:
        prefs = preferences.load(session)
        prefs.replace_automatically = True
        preferences.save(session, prefs)
    inbox_job.start(settings)
    inbox_job.wait(30)
    assert (settings.music_dir / FLAC_PATH).exists() and not (settings.music_dir / MP3).exists()
    assert inbox_job.auto_upgrade.written == 1


def test_automatic_replacing_never_fills_gaps_with_guesses(engine, settings, inbox, library):
    tags = ID3(settings.music_dir / MP3)
    tags.delall("TBPM")  # the library copy has no BPM
    tags.save()
    scan_library(engine, settings.music_dir, ScanProgress())
    analysis.analyse_track(engine, settings, inbox, False, False)  # 87 BPM, not sure
    with Session(engine) as session:
        (better,) = upgrade.upgrades(session, settings)
        assert upgrade.plan(session, better, settings).changes["bpm"] == "87"  # Replace: shown
        assert not upgrade.ready_for_auto_upgrade(session, better, settings, time.time())

        save_values(session, session.get(InboxTrack, inbox), {"bpm": "174"})  # the owner's
        (better,) = upgrade.upgrades(session, settings)
        assert upgrade.ready_for_auto_upgrade(session, better, settings, time.time())

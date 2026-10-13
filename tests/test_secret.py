"""Secret tracks: edits and bootlegs, never looked up online, complete without a cover."""

import json
import os
import re
import shutil
import time

import pytest
from mutagen.id3 import ID3
from sqlmodel import Session, select

from app import analysis, final, identify, secret
from app.changes import WriteProgress
from app.importer import import_tracks
from app.inbox import scan_inbox
from app.library import FLAGS, MISSING, SET_READY, TrackFilter, count, find_tracks
from app.models import (
    ChangeSet,
    FinalTrack,
    InboxTrack,
    LibraryAnalysis,
    LibraryLookup,
    OnlineLookup,
    SecretInboxTrack,
    SecretTrack,
    Track,
)
from app.scanner import ScanProgress, scan_library
from app.undo import undo_changeset
from app.work import _ready
from tests.conftest import FIXTURES
from tests.test_identify import inbox_fixture, web  # noqa: F401  (saved answers, no internet)

BOOTLEG = "Edits/bootleg.mp3"


def without_cover(path):
    """A copy of tagged.mp3 (title, artist, genre, BPM, key) without its cover."""
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "tagged.mp3", path)
    tags = ID3(path)
    tags.delall("APIC")
    tags.save()


@pytest.fixture
def bootleg(engine, settings) -> int:
    """A library track with every DJ tag but no cover."""
    without_cover(settings.music_dir / BOOTLEG)
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        return session.exec(select(Track.id).where(Track.path == BOOTLEG)).one()


def is_set_ready(engine, track_id) -> bool:
    with Session(engine) as session:
        return bool(session.exec(select(Track.id).where(Track.id == track_id, SET_READY)).first())


# --- The mark itself -------------------------------------------------------------------------


def test_files_in_the_secret_folder_arrive_secret(engine, settings):
    root = settings.import_dir
    for path in ("Secret/Bootlegs/a.mp3", "secret/b.mp3", "c.mp3", "Not Secret/d.mp3"):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURES / "untagged.mp3", root / path)
    shutil.copy(FIXTURES / "untagged.mp3", root / "Secret.mp3")  # a file, not the folder
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        marked = session.exec(
            select(InboxTrack.path).join(
                SecretInboxTrack, SecretInboxTrack.track_id == InboxTrack.id
            )
        ).all()
    assert sorted(marked) == ["Secret/Bootlegs/a.mp3", "secret/b.mp3"]


def test_the_folder_marks_only_new_files(engine, settings):
    """A track the owner took the mark off stays unmarked when the inbox is checked again."""
    root = settings.import_dir
    (root / "Secret").mkdir(parents=True)
    shutil.copy(FIXTURES / "untagged.mp3", root / "Secret" / "a.mp3")
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        track_id = session.exec(select(InboxTrack.id)).one()
        secret.unmark(session, [track_id], inbox=True)
    os.utime(root / "Secret" / "a.mp3")  # changed: read again
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        assert not secret.is_secret(session, track_id, inbox=True)


# --- Never looked up online ------------------------------------------------------------------


def test_secret_inbox_tracks_are_never_looked_up(web, engine, settings, monkeypatch):  # noqa: F811
    from app.jobs import identify_job

    track = inbox_fixture(engine, settings, monkeypatch)
    with Session(engine) as session:
        secret.mark(session, [track], inbox=True)
    assert identify.lookup(engine, settings, track, force=True) == 0
    identify_job.start(settings)  # the inbox check's lookups
    identify_job.start(settings, [track], force=True)  # "Look up again"
    identify_job.wait(10)
    assert web == []  # no source was asked, not even AcoustID with the audio
    with Session(engine) as session:
        assert not session.exec(select(OnlineLookup)).all()


def test_marking_forgets_what_was_found_online(web, engine, settings, monkeypatch):  # noqa: F811
    track = inbox_fixture(engine, settings, monkeypatch)
    identify.lookup(engine, settings, track)
    with Session(engine) as session:
        assert identify.suggestions(session, session.get(InboxTrack, track), taken=set())
        secret.mark(session, [track], inbox=True)
        assert not session.exec(select(OnlineLookup)).all()
        assert identify.suggestions(session, session.get(InboxTrack, track), taken=set()) == []
        assert identify.cover_suggestion(session, session.get(InboxTrack, track)) is None


def test_a_track_marked_during_its_lookup_keeps_no_answers(web, engine, settings, monkeypatch):  # noqa: F811
    from app.sources.base import Source

    track = inbox_fixture(engine, settings, monkeypatch)
    answer = Source.get_json

    def mark_while_asking(self, url, params=None, headers=None):
        with Session(engine) as session:  # the owner flips the switch meanwhile
            secret.mark(session, [track], inbox=True)
        return answer(self, url, params, headers)

    monkeypatch.setattr(Source, "get_json", mark_while_asking)
    identify.lookup(engine, settings, track)
    assert len(web) == 1  # the first source's answer came in; nobody else was asked
    with Session(engine) as session:
        assert not session.exec(select(OnlineLookup)).all()


def test_library_lookups_skip_secret_tracks(client, engine, settings, bootleg):
    from app.jobs import identify_job

    with Session(engine) as session:
        other = session.exec(select(Track.id).where(Track.path != BOOTLEG)).first()
        session.add(LibraryLookup(track_id=bootleg, source="deezer", query="{}"))
        session.commit()
    response = client.post(
        "/api/tracks/secret", json={"track_ids": [bootleg], "secret": True}
    ).json()
    assert response == {"changed": 1}
    with Session(engine) as session:  # what was found before is forgotten
        assert not session.exec(select(LibraryLookup)).all()

    looked = client.post("/tracks/lookup", data={"ids": [str(bootleg), str(other)]})
    assert "looking=1&skipped_secret=1" in str(looked.url)
    assert "1 secret track was left out" in looked.text
    one = client.post(f"/tracks/{bootleg}/lookup")
    assert "looking" not in str(one.url)
    api = client.post("/api/tracks/lookup", json={"track_ids": [bootleg]}).json()
    assert (api["tracks"], api["skipped_secret"]) == (0, 1)
    identify_job.wait(10)
    with Session(engine) as session:
        asked = set(session.exec(select(LibraryLookup.track_id)))
    assert bootleg not in asked and other in asked


def test_marking_decides_bpm_again_without_the_online_hints(client, engine, bootleg):
    candidate = {"source": "deezer", "values": {"bpm": "99"}, "score": 1.0}
    with Session(engine) as session:
        session.add(LibraryAnalysis(track_id=bootleg, bpm=128.0, duration=30.0))
        session.add(LibraryLookup(track_id=bootleg, source="deezer", query='["A", "T", 0]',
                                  candidates=json.dumps([candidate])))  # fmt: skip
        analysis.refresh(session, session.get(Track, bootleg))
        session.commit()
        assert "says 99 BPM" in session.get(LibraryAnalysis, bootleg).decided_notes

    client.post("/api/tracks/secret", json={"track_ids": [bootleg], "secret": True})
    with Session(engine) as session:
        assert "says 99 BPM" not in session.get(LibraryAnalysis, bootleg).decided_notes


# --- Complete without a cover ----------------------------------------------------------------


def test_a_secret_track_is_set_ready_and_final_without_a_cover(engine, settings, bootleg):
    assert not is_set_ready(engine, bootleg)
    with Session(engine) as session:
        missing_cover = count(session, MISSING["Cover art"])
        secret.mark(session, [bootleg])
        assert count(session, MISSING["Cover art"]) == missing_cover - 1
        assert session.exec(select(Track.id).where(Track.id == bootleg, final.READY)).first()
        listed = find_tracks(session, TrackFilter(flag="secret")).tracks
        assert [t.id for t in listed] == [bootleg]
        assert count(session, FLAGS["secret"][1]) == 1
    assert is_set_ready(engine, bootleg)

    final.mark(engine, settings, bootleg, WriteProgress(action="final"))
    with Session(engine) as session:
        assert session.get(FinalTrack, bootleg)


def test_set_ready_before_and_after_counts_the_mark():
    track = Track(path="a.mp3", format="mp3", size=1, mtime=1, title="T", artist="A",
                  genre="House", bpm=124, key="Am", key_camelot="8A")  # fmt: skip
    assert not _ready(track, {})
    assert _ready(track, {}, is_secret=True)
    assert not _ready(track, {"genre": None}, is_secret=True)  # the rest is still needed


def test_inbox_tracks_need_no_cover_when_secret(client, settings):
    from app.jobs import inbox_job

    root = settings.import_dir
    without_cover(root / "Secret" / "bootleg.mp3")
    without_cover(root / "official.mp3")
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    rows = {t["path"]: t for t in client.get("/api/inbox").json()}
    assert rows["Secret/bootleg.mp3"]["secret"] is True
    assert "Cover" not in rows["Secret/bootleg.mp3"]["missing"]
    assert "Cover" not in rows["Secret/bootleg.mp3"]["still_missing"]
    assert rows["official.mp3"]["secret"] is False
    assert "Cover" in rows["official.mp3"]["still_missing"]


def test_automatic_import_takes_secret_tracks_without_a_cover(client, settings):
    from app.jobs import analysis_job, inbox_job

    root = settings.import_dir
    without_cover(root / "Secret" / "bootleg.mp3")
    without_cover(root / "official.mp3")
    old = time.time() - 600
    for path in (root / "Secret" / "bootleg.mp3", root / "official.mp3"):
        os.utime(path, (old, old))
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    analysis_job.wait(60)  # automatic import waits for BPM and key from the audio

    prefs = client.get("/api/settings").json() | {"automation": "auto"}
    client.put("/api/settings", json=prefs)
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    assert [t["path"] for t in client.get("/api/inbox").json()] == ["official.mp3"]
    imported = client.get("/api/tracks", params={"flag": "secret"}).json()["tracks"]
    assert [t["path"].rsplit("/", 1)[-1] for t in imported] == ["bootleg.mp3"]
    assert imported[0]["secret"] is True


# --- The mark moves with the track -------------------------------------------------------------


@pytest.mark.parametrize("folder", ["Secret/", ""])
def test_the_mark_moves_through_import_and_undo(engine, settings, folder):
    """Into the library on import, back into the inbox on undo: from the Secret folder, and
    when the owner marked a track somewhere else."""
    root = settings.import_dir
    path = f"{folder}Artist - Bootleg.mp3"
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "untagged.mp3", root / path)
    scan_inbox(engine, root, ScanProgress())
    with Session(engine) as session:
        inbox_id = session.exec(select(InboxTrack.id)).one()
        secret.mark(session, [inbox_id], inbox=True)  # already marked in the Secret folder

    progress = WriteProgress(action="import")
    import_tracks(engine, root, settings.music_dir, [inbox_id], progress)
    assert progress.written == 1
    with Session(engine) as session:
        track = session.exec(select(Track)).one()
        assert session.get(SecretTrack, track.id)
        changeset_id = session.exec(select(ChangeSet.id)).one()

    undo_changeset(
        engine, settings.music_dir, changeset_id, WriteProgress(action="undo"), import_dir=root
    )
    with Session(engine) as session:
        back = session.exec(select(InboxTrack).where(InboxTrack.path == path)).one()
        assert session.get(SecretInboxTrack, back.id)
        assert not session.exec(select(SecretTrack)).all()
    scan_inbox(engine, root, ScanProgress())  # the next inbox check keeps it
    with Session(engine) as session:
        back = session.exec(select(InboxTrack).where(InboxTrack.path == path)).one()
        assert secret.is_secret(session, back.id, inbox=True)


def test_a_moved_file_keeps_its_mark(engine, settings, bootleg):
    with Session(engine) as session:
        secret.mark(session, [bootleg])
    (settings.music_dir / "Moved").mkdir()
    os.rename(settings.music_dir / BOOTLEG, settings.music_dir / "Moved" / "bootleg.mp3")
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        assert session.get(Track, bootleg).path == "Moved/bootleg.mp3"
        assert secret.is_secret(session, bootleg)


# --- Pages -----------------------------------------------------------------------------------


def test_track_page_switch(client, engine, bootleg):
    page = client.get(f"/tracks/{bootleg}").text
    assert 'class="secret-switch"' in page and "Edit or bootleg?" in page
    assert f'action="/tracks/{bootleg}/lookup"' in page

    marked = client.post(f"/tracks/{bootleg}/secret", data={"secret": "1", "back": "/tracks"})
    assert "secret_on=1" in str(marked.url) and "back=%2Ftracks" in str(marked.url)
    assert "Marked 1 track as secret" in marked.text
    assert "Not asked: the track is secret" in marked.text
    assert f'action="/tracks/{bootleg}/lookup"' not in marked.text  # no Look up button
    assert re.search(r'role="switch" checked', marked.text)
    assert client.get(f"/api/tracks/{bootleg}").json()["secret"] is True

    unmarked = client.post(f"/tracks/{bootleg}/secret", data={"secret": "0"})
    assert "Removed the secret mark from 1 track" in unmarked.text
    assert client.get(f"/api/tracks/{bootleg}").json()["secret"] is False


def test_track_list_marks_and_unmarks_ticked_tracks(client, engine, bootleg):
    page = client.get("/tracks").text
    assert 'id="secret-selected"' in page and ">Mark as secret</button>" in page
    client.post("/tracks/secret", data={"ids": [str(bootleg)], "secret": "1"})
    listed = client.get("/tracks?flag=secret").text
    assert "status-secret" in listed and ">Not secret</button>" in listed
    assert 'id="lookup-selected"' not in listed  # secret tracks are never looked up
    assert "Secret tracks</strong> are edits and bootlegs" in listed
    client.post("/tracks/secret", data={"ids": [str(bootleg)], "secret": "0"})
    assert client.get("/api/tracks", params={"flag": "secret"}).json()["total"] == 0


def test_final_check_shows_a_secret_track_without_a_cover(client, engine, bootleg):
    client.post("/api/tracks/secret", json={"track_ids": [bootleg]})
    page = client.get(f"/final?id={bootleg}").text
    assert "status-secret" in page and "cover-missing" in page
    assert f'src="/tracks/{bootleg}/cover' not in page  # no broken image


def test_statistics_explain_the_covers_not_counted(client, engine, bootleg):
    client.post("/api/tracks/secret", json={"track_ids": [bootleg]})
    page = client.get("/stats").text
    assert "1 secret track</a> (edits, bootlegs): no cover needed" in page


def test_inbox_pages(client, engine, settings):
    from app.jobs import identify_job, inbox_job

    root = settings.import_dir
    (root / "Secret").mkdir(parents=True)
    shutil.copy(FIXTURES / "untagged.mp3", root / "Secret" / "a.mp3")
    shutil.copy(FIXTURES / "untagged.mp3", root / "b.mp3")
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    identify_job.wait(30)
    ids = {t["path"]: t["id"] for t in client.get("/api/inbox").json()}
    a, b = ids["Secret/a.mp3"], ids["b.mp3"]

    page = client.get("/inbox").text
    assert 'data-view="secret"' in page and "status-secret" in page
    assert 'id="inbox-secret-button"' in page
    review = client.get(f"/inbox/{a}").text
    assert "Not asked: the track is secret" in review
    assert re.search(r'role="switch" checked', review)
    assert f'action="/inbox/{a}/lookup"' not in review

    client.post(f"/inbox/{b}/secret", data={"secret": "1"})
    marked = client.post("/inbox/secret", data={"ids": [str(a), str(b)], "secret": "1"})
    assert "Nothing changed: already secret" in marked.text
    with Session(engine) as session:
        assert secret.secret_ids(session, [a, b], inbox=True) == {a, b}
        assert not session.exec(select(OnlineLookup).where(OnlineLookup.track_id == a)).all()

    # Without the mark, a track is looked up at once, like any new inbox track.
    response = client.post("/api/inbox/secret", json={"track_ids": [a], "secret": False})
    assert response.json() == {"changed": 1}
    identify_job.wait(30)
    with Session(engine) as session:
        assert session.exec(select(OnlineLookup).where(OnlineLookup.track_id == a)).all()
    assert client.post(f"/api/inbox/{b}/lookup").status_code == 409


def test_settings_explain_secret_tracks(client):
    page = client.get("/settings").text
    assert "tracks are never looked up" in page and "<code>Secret</code>" in page


def test_the_secret_hint_can_be_hidden_for_good(client, settings):
    settings.import_dir.mkdir(parents=True)
    page = client.get("/inbox").text
    assert 'id="hint-secret"' in page and "Don't show again" in page

    assert client.post("/hints/unknown", headers={"HX-Request": "true"}).text == ""
    assert client.get("/api/settings").json()["hidden_hints"] == []  # only known messages
    hidden = client.post("/hints/secret", headers={"HX-Request": "true"})
    assert hidden.text == ""  # htmx removes the message in place
    assert client.get("/api/settings").json()["hidden_hints"] == ["secret"]
    assert 'id="hint-secret"' not in client.get("/inbox").text

    client.put("/api/settings", json=client.get("/api/settings").json() | {"hidden_hints": []})
    without_js = client.post("/hints/secret", headers={"referer": "http://testserver/inbox"})
    assert str(without_js.url).endswith("/inbox") and 'id="hint-secret"' not in without_js.text


def test_the_hint_is_the_same_on_the_secret_track_list(client, engine, bootleg):
    client.post("/api/tracks/secret", json={"track_ids": [bootleg]})
    assert 'id="hint-secret"' in client.get("/tracks?flag=secret").text
    client.post("/hints/secret", headers={"HX-Request": "true"})
    assert 'id="hint-secret"' not in client.get("/tracks?flag=secret").text

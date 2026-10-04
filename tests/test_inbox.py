import os
import re
import shutil

import pytest
from sqlmodel import Session, select

from app.inbox import missing, scan_inbox
from app.jobs import inbox_job, scan_job
from app.models import InboxTrack, Track
from app.scanner import ScanProgress
from app.tags import read_file
from tests.conftest import FIXTURES


@pytest.fixture
def import_dir(settings):
    root = settings.import_dir
    (root / "Pool Downloads").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "tagged.mp3", root / "Pool Downloads" / "Artist - Title (Extended Mix).mp3"
    )
    shutil.copy(FIXTURES / "untagged.mp3", root / "promo.mp3")
    (root / "notes.txt").write_text("not audio")
    return root


def scan(engine, import_dir) -> ScanProgress:
    progress = ScanProgress()
    scan_inbox(engine, import_dir, progress)
    return progress


def test_scan_reads_new_files_and_forgets_removed_ones(engine, import_dir):
    progress = scan(engine, import_dir)
    assert (progress.added, progress.removed) == (2, 0)
    with Session(engine) as session:
        tagged = session.exec(select(InboxTrack).where(InboxTrack.path.startswith("Pool"))).one()
        assert (tagged.title, tagged.bpm, tagged.key_camelot) == ("Silent Track", 126.0, "8A")

    assert scan(engine, import_dir).unchanged == 2  # unchanged files aren't read again

    (import_dir / "promo.mp3").unlink()
    assert scan(engine, import_dir).removed == 1


def test_changed_files_are_read_again(engine, import_dir):
    scan(engine, import_dir)
    path = import_dir / "promo.mp3"
    shutil.copy(FIXTURES / "tagged.mp3", path)
    os.utime(path, (5, 5))
    assert scan(engine, import_dir).updated == 1
    with Session(engine) as session:
        assert session.exec(select(InboxTrack).where(InboxTrack.path == "promo.mp3")).one().title


def test_unreadable_files_are_listed(engine, import_dir):
    (import_dir / "broken.flac").write_bytes(b"not really flac")
    scan(engine, import_dir)
    with Session(engine) as session:
        broken = session.exec(select(InboxTrack).where(InboxTrack.path == "broken.flac")).one()
        assert broken.error and missing(broken) == ["Unreadable"]


def test_missing_lists_what_a_track_lacks(engine, import_dir):
    scan(engine, import_dir)
    with Session(engine) as session:
        untagged = session.exec(select(InboxTrack).where(InboxTrack.path == "promo.mp3")).one()
    assert missing(untagged) == ["Title", "Artist", "Genre", "BPM", "Key", "Cover"]


def test_inbox_tracks_stay_out_of_the_library(client, engine, import_dir):
    client.post("/api/scan")
    scan_job.wait(30)
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    with Session(engine) as session:
        assert not session.exec(select(Track).where(Track.path.contains("Extended Mix"))).all()
    assert all("Extended Mix" not in t["path"] for t in client.get("/api/tracks").json()["tracks"])
    assert len(client.get("/api/inbox").json()) == 2


def test_inbox_page(client, import_dir):
    inbox_job.finished_at = None  # as after a restart: opening the page starts a check
    client.get("/inbox")
    assert inbox_job.status in ("running", "done")
    inbox_job.wait(30)
    page = client.get("/inbox").text
    assert "Artist - Title (Extended Mix).mp3" in page and "2 tracks" in page
    assert 'aria-label="2 tracks"' in client.get("/").text  # menu badge


def test_inbox_page_without_import_folder(client):
    page = client.get("/inbox").text
    assert "No import folder yet" in page and "Import Inbox" in page


def test_review_page_shows_suggestions_and_saves_corrections(client, engine, import_dir):
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    with Session(engine) as session:
        promo = session.exec(select(InboxTrack).where(InboxTrack.path == "promo.mp3")).one()
        pool = session.exec(select(InboxTrack).where(InboxTrack.path.startswith("Pool"))).one()

    page = client.get(f"/inbox/{promo.id}").text
    assert 'value="Promo"' in page and "Suggested · from filename" in page

    bad = client.post(f"/inbox/{promo.id}", data={"bpm": "fast"})
    assert bad.status_code == 422 and "BPM must be a number" in bad.text

    saved = client.post(
        f"/inbox/{promo.id}",
        data={"title": "Real Title", "artist": "Real Artist", "then": "list"},
        follow_redirects=False,
    )
    assert saved.headers["location"] == "/inbox?kept=1"
    page = client.get(f"/inbox/{promo.id}").text
    assert 'value="Real Title"' in page and "Your value" in page
    assert "edited" in client.get("/inbox").text

    # Typing the suggestion again just follows the suggestion; reset forgets everything.
    client.post(f"/inbox/{promo.id}", data={"title": "Promo"})
    page = client.get(f"/inbox/{promo.id}").text
    assert 'value="Promo"' in page and 'value="Real Artist"' in page
    client.post(f"/inbox/{promo.id}", data={"reset": "1"})
    assert "Your value" not in client.get(f"/inbox/{promo.id}").text

    # The file itself is untouched until import.
    assert read_file(import_dir / "promo.mp3").title is None
    assert client.get(f"/inbox/{pool.id}/cover").headers["content-type"].startswith("image/")


def test_save_and_next_goes_to_the_next_track(client, import_dir):
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    ids = [t["id"] for t in client.get("/api/inbox").json()]
    first = client.get("/inbox").text.index(f'/inbox/{ids[0]}"') < client.get("/inbox").text.index(
        f'/inbox/{ids[1]}"'
    )
    a, b = (ids[0], ids[1]) if first else (ids[1], ids[0])
    saved = client.post(f"/inbox/{a}", data={"then": "next"}, follow_redirects=False)
    assert saved.headers["location"] == f"/inbox/{b}?kept=1"


def test_inbox_note_is_not_about_pending_changes(client, import_dir):
    page = client.get("/inbox?kept=1").text
    assert "Written into the file when you import" in page and "pending change" not in page


def test_tabs_filter_the_list_and_save_and_next_stays_in_the_tab(client, import_dir):
    shutil.copy(FIXTURES / "untagged.mp3", import_dir / "another promo.mp3")
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    tracks = {t["path"]: t["id"] for t in client.get("/api/inbox").json()}
    promo, another = tracks["promo.mp3"], tracks["another promo.mp3"]

    client.post(f"/inbox/{promo}", data={"artist": "Someone"})  # now "edited"
    page = client.get("/inbox?show=edited").text
    assert 'aria-current="page">Edited' in page
    # Every track is on the page (so ticks survive switching tabs); the others are hidden.
    rows = dict(
        (int(track_id), hidden)
        for hidden, track_id in re.findall(
            r'<tr data-views="[^"]*"( hidden)?>\s*<td class="check-col"><input[^>]*value="(\d+)"',
            page,
        )
    )
    assert [i for i, hidden in rows.items() if not hidden] == [promo]  # only the edited one
    assert len(rows) == len(tracks)
    assert f"/inbox/{promo}?show=edited" in page

    # From "Needs help": the next track is the next one that needs help.
    help_page = client.get("/inbox?show=help").text
    order = [i for i in (promo, another) if f"/inbox/{i}?show=help" in help_page]
    assert len(order) == 2
    first = min(order, key=lambda i: help_page.index(f"/inbox/{i}?show=help"))
    second = max(order, key=lambda i: help_page.index(f"/inbox/{i}?show=help"))
    saved = client.post(
        f"/inbox/{first}", data={"then": "next", "show": "help"}, follow_redirects=False
    )
    assert saved.headers["location"] == f"/inbox/{second}?kept=1&show=help"


def test_an_empty_tab_is_not_an_empty_inbox(client, import_dir):
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    page = client.get("/inbox?show=edited").text  # nothing edited yet
    assert "The inbox is empty" not in page and "No tracks here right now" in page

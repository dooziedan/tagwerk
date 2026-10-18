"""Notifications: what Tagwerk did while the owner was away (app/notifications.py, ADR 0035)."""

from dataclasses import replace

from sqlmodel import Session, select

from app import notifications, preferences
from app.models import Notification
from app.notifications import TOPICS


def _all(engine) -> list[Notification]:
    with Session(engine) as session:
        return list(session.exec(select(Notification).order_by(Notification.id)))


def _switch(engine, **topics: bool) -> None:
    with Session(engine) as session:
        prefs = preferences.load(session)
        preferences.save(session, replace(prefs, notifications=prefs.notifications | topics))


def test_a_fresh_install_has_only_the_topics_that_need_you_switched_on(engine):
    with Session(engine) as session:
        chosen = preferences.load(session).notifications
    assert chosen == {
        "inbox_trash": True,
        "inbox_help": True,
        "scan": True,
        "navidrome": True,
        "online": True,
        "auto_import": False,
        "auto_upgrade": False,
        "long_jobs": False,
    }
    assert set(chosen) == set(TOPICS)


def test_notify_writes_one_unread_entry(engine):
    assert notifications.notify(
        "scan", "problem", "Scan skipped", "The music folder looks empty.", url="/scan"
    )
    [note] = _all(engine)
    assert (note.topic, note.kind, note.summary, note.url) == (
        "scan",
        "problem",
        "Scan skipped",
        "/scan",
    )
    assert note.source == "Scan problems"  # the topic's name unless a source is given
    assert note.read_at is None
    with Session(engine) as session:
        assert notifications.unread_count(session) == 1
        assert notifications.unread_count(session, "needs_you") == 0


def test_a_switched_off_topic_writes_nothing(engine):
    assert not notifications.notify("auto_import", "done", "4 tracks imported")  # off by default
    _switch(engine, scan=False)
    assert not notifications.notify("scan", "problem", "Scan skipped")
    assert _all(engine) == []


def test_notify_never_raises(engine, monkeypatch, caplog):
    """A notification that can't be written (here: the database is locked) doesn't stop the
    job that wanted to write it."""

    def locked(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(notifications, "_write", locked)
    assert notifications.notify("scan", "problem", "Scan skipped") is False
    assert notifications.problem("navidrome", "navidrome", "Navidrome didn't answer") is False
    assert "Could not write the notification" in caplog.text
    assert notifications.notify("no-such-topic", "done", "x") is False


def test_a_lasting_problem_is_reported_once_and_once_when_it_is_fine_again(engine):
    assert notifications.problem("navidrome", "navidrome", "Navidrome didn't answer")
    assert not notifications.problem("navidrome", "navidrome", "Navidrome didn't answer")
    assert notifications.solved("navidrome", "navidrome", "Navidrome answers again")
    assert not notifications.solved("navidrome", "navidrome", "Navidrome answers again")
    assert [(n.kind, n.summary) for n in _all(engine)] == [
        ("problem", "Navidrome didn't answer"),
        ("done", "Navidrome answers again"),
    ]
    assert notifications.problem("navidrome", "navidrome", "Navidrome didn't answer")  # again
    assert len(_all(engine)) == 3


def test_read_ones_stay_in_new_until_cleared_and_only_clear_history_removes(engine):
    """ADR 0043: opening marks as read; clearing moves to the History; nothing goes by itself."""
    for n in range(3):
        notifications.notify("scan", "problem", f"Problem {n}")
    first, second, third = _all(engine)

    def summaries(notes):
        return [n.summary for n in notes]

    with Session(engine) as session:
        assert summaries(notifications.current(session)) == ["Problem 2", "Problem 1", "Problem 0"]
        assert notifications.mark_read(session, second.id).read_at
        assert notifications.unread_count(session) == 2
        assert summaries(notifications.unread(session)) == ["Problem 2", "Problem 0"]  # the menu
        assert summaries(notifications.current(session)) == ["Problem 2", "Problem 1", "Problem 0"]
        assert notifications.history(session) == []

        cleared = notifications.clear(session, third.id)  # unread: clearing reads it too
        assert cleared.cleared_at and cleared.read_at
        assert notifications.unread_count(session) == 1
        assert summaries(notifications.current(session)) == ["Problem 1", "Problem 0"]
        assert summaries(notifications.history(session)) == ["Problem 2"]

        assert notifications.clear_history(session) == 1  # only the cleared one goes
        assert summaries(notifications.current(session)) == ["Problem 1", "Problem 0"]

        assert notifications.mark_all_read(session) == 1
        assert notifications.unread_count(session) == 0
        assert len(notifications.current(session)) == 2  # read, still in New
        assert notifications.clear_all(session) == 2
        assert notifications.current(session) == []
        assert summaries(notifications.history(session)) == ["Problem 1", "Problem 0"]
        for missing in (notifications.mark_read, notifications.mark_unread, notifications.clear):
            assert missing(session, 999) is None


def test_mark_as_unread_counts_again_and_brings_a_cleared_one_back(engine):
    notifications.notify("scan", "problem", "Scan skipped")
    (note,) = _all(engine)
    with Session(engine) as session:
        notifications.clear(session, note.id)
        back = notifications.mark_unread(session, note.id)
        assert back.read_at is None and back.cleared_at is None
        assert notifications.unread_count(session) == 1
        assert [n.summary for n in notifications.current(session)] == ["Scan skipped"]
        assert notifications.history(session) == []


def test_checks_remember_values_between_runs(engine):
    assert notifications.recall("inbox_help", 0) == 0
    notifications.remember("inbox_help", 3)
    assert notifications.recall("inbox_help", 0) == 3


# --- Inbox trash: announced 3 days before the files go, each file once ------------------------


def test_inbox_trash_files_are_announced_three_days_before_once(engine, settings):
    from datetime import UTC, datetime, timedelta

    from app import reminders, trash

    settings.import_dir.mkdir()
    for name in ("old.mp3", "older.mp3"):
        (settings.import_dir / name).write_bytes(b"x")
        trash.delete(settings.import_dir, name)
    deleted = datetime.now(UTC)
    ten_days_left = deleted + timedelta(days=trash.KEEP_DAYS - 10)
    assert not reminders.announce_inbox_trash(settings, ten_days_left)  # not yet

    two_days_left = deleted + timedelta(days=trash.KEEP_DAYS - 2)
    assert reminders.announce_inbox_trash(settings, two_days_left)
    [note] = _all(engine)
    assert note.kind == "needs_you" and note.url == "/inbox#trash"
    assert note.summary.startswith("Inbox trash: 2 files will be removed for good on ")
    assert "old.mp3" in note.message and "older.mp3" in note.message

    # A file that comes due after today's check waits for tomorrow's (one entry a day at most),
    # and tomorrow only it is announced: each file once.
    (settings.import_dir / "late.mp3").write_bytes(b"x")
    trash.delete(settings.import_dir, "late.mp3")
    assert not reminders.announce_inbox_trash(settings, two_days_left + timedelta(minutes=5))
    assert reminders.announce_inbox_trash(settings, two_days_left + timedelta(days=1))
    late = _all(engine)[-1]
    assert late.summary.startswith("Inbox trash: 1 file will be removed for good on ")
    assert "late.mp3" in late.message and "old" not in late.message

    # After removal nothing is said: it would be too late.
    trash.purge(settings.import_dir, deleted + timedelta(days=trash.KEEP_DAYS + 1))
    assert not reminders.announce_inbox_trash(settings, deleted + timedelta(days=40))
    assert len(_all(engine)) == 2


def test_inbox_trash_dates_are_in_the_owners_time_zone(engine, settings):
    """Settings → General → Time zone: near midnight the day depends on it."""
    from datetime import UTC, datetime

    from app import reminders

    late_evening = datetime(2026, 10, 13, 23, 30, tzinfo=UTC)
    with Session(engine) as session:
        prefs = preferences.load(session)
        assert prefs.time_zone == ""  # the container's
        prefs = preferences.save(session, replace(prefs, time_zone="Europe/Berlin"))
    assert reminders._day(late_evening, preferences.zone(prefs)) == "14 Oct"
    assert reminders._day(late_evening, preferences.zone(replace(prefs, time_zone="UTC"))) == (
        "13 Oct"
    )
    with Session(engine) as session:
        preferences.save(session, replace(prefs, time_zone="Mars/Olympus_Mons"))
        assert preferences.load(session).time_zone == ""  # unknown: back to the container's


def test_settings_save_the_time_zone(client, engine):
    page = client.get("/settings").text
    assert 'id="general"' in page and '<select name="time_zone"' in page
    assert "<option>Europe/Berlin</option>" in page
    response = client.post("/settings", data={"time_zone": "Europe/Berlin"})
    assert response.url.query == b"saved=general"
    with Session(engine) as session:
        assert preferences.load(session).time_zone == "Europe/Berlin"
    assert "<option selected>Europe/Berlin</option>" in client.get("/settings").text


def test_the_restore_link_opens_the_inbox_trash(client, settings):
    from app import trash

    settings.import_dir.mkdir()
    (settings.import_dir / "gone.mp3").write_bytes(b"x")
    trash.delete(settings.import_dir, "gone.mp3")
    page = client.get("/inbox").text
    assert '<details id="trash"' in page and "gone.mp3" in page


def test_inbox_trash_switched_off_writes_nothing(engine, settings):
    from datetime import UTC, datetime, timedelta

    from app import reminders, trash

    _switch(engine, inbox_trash=False)
    settings.import_dir.mkdir()
    (settings.import_dir / "old.mp3").write_bytes(b"x")
    trash.delete(settings.import_dir, "old.mp3")
    now = datetime.now(UTC) + timedelta(days=trash.KEEP_DAYS - 1)
    assert not reminders.announce_inbox_trash(settings, now)
    assert _all(engine) == []


# --- Inbox: tracks need your help, only when the number goes up ---------------------------------


def test_inbox_help_is_reported_only_when_the_number_goes_up(engine, settings):
    import shutil

    from app import reminders
    from app.inbox import scan_inbox
    from app.scanner import ScanProgress
    from tests.conftest import FIXTURES

    settings.import_dir.mkdir()
    assert not reminders.report_inbox_help(settings)  # an empty inbox: nothing
    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / "promo one.mp3")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    assert reminders.report_inbox_help(settings)
    assert not reminders.report_inbox_help(settings)  # the same number: nothing new

    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / "promo two.mp3")
    scan_inbox(engine, settings.import_dir, ScanProgress())
    assert reminders.report_inbox_help(settings)
    first, second = _all(engine)
    assert first.summary == "Inbox: 1 track needs your help"
    assert second.summary == "Inbox: 1 more track needs your help"
    assert second.kind == "needs_you" and second.url == "/inbox?show=help"
    assert "2 tracks in the inbox need your help now" in second.message

    (settings.import_dir / "promo two.mp3").unlink()  # fewer: nothing, but remembered
    scan_inbox(engine, settings.import_dir, ScanProgress())
    assert not reminders.report_inbox_help(settings)
    assert notifications.recall("inbox_help:count") == 1


def test_inbox_help_waits_while_lookups_run(engine, settings, monkeypatch):
    from app import reminders
    from app.jobs import identify_job

    settings.import_dir.mkdir()
    monkeypatch.setattr(type(identify_job), "running", property(lambda self: True))
    assert not reminders.report_inbox_help(settings)
    assert notifications.recall("inbox_help:count") is None  # not even counted


# --- Scan: skipped (folder looks empty), files that couldn't be read ---------------------------


def test_a_skipped_scan_is_reported_once_and_once_when_scans_work_again(engine, settings):
    import shutil

    from app.jobs import scan_job

    scan_job.start(settings)
    scan_job.wait(30)
    assert _all(engine) == []  # a scan where nothing went wrong writes nothing

    backup = settings.music_dir.with_name("backup")
    shutil.move(settings.music_dir, backup)
    settings.music_dir.mkdir()  # mounted, but empty
    for _ in range(2):
        scan_job.start(settings)
        scan_job.wait(30)
        assert scan_job.status == "failed"
    [note] = _all(engine)
    assert note.kind == "problem" and note.summary == "Scan skipped: the music folder looks empty"
    assert "Is the music share mounted" in note.message

    settings.music_dir.rmdir()
    shutil.move(backup, settings.music_dir)
    scan_job.start(settings)
    scan_job.wait(30)
    assert [n.summary for n in _all(engine)] == [note.summary, "Scans work again"]


def test_unreadable_files_are_reported_once_each(engine, settings):
    from app.jobs import scan_job

    (settings.music_dir / "broken.mp3").write_bytes(b"not really audio" * 100)
    scan_job.start(settings)
    scan_job.wait(30)
    scan_job.start(settings)  # tried again, still broken: not reported again
    scan_job.wait(30)
    [note] = _all(engine)
    assert note.summary == "Scan: 1 file couldn't be read" and "broken.mp3" in note.message
    assert note.url == "/tracks?flag=unreadable"

    (settings.music_dir / "broken too.mp3").write_bytes(b"not really audio" * 100)
    scan_job.start(settings)
    scan_job.wait(30)
    assert "broken too.mp3" in _all(engine)[-1].message
    assert "broken.mp3" not in _all(engine)[-1].message.replace("broken too.mp3", "")


# --- Navidrome: didn't answer (once while it lasts) ------------------------------------------


def test_navidrome_not_answering_is_reported_once(engine, settings, monkeypatch):
    from app import navidrome

    monkeypatch.setattr(settings, "navidrome_url", "http://192.168.1.10:4533")
    monkeypatch.setattr(settings, "navidrome_user", "admin")
    monkeypatch.setattr(settings, "navidrome_password", "secret")
    answer = {
        "result": navidrome.Result(False, "Can't reach Navidrome at http://192.168.1.10:4533.")
    }
    monkeypatch.setattr(navidrome, "_call", lambda *args, **kwargs: (answer["result"], {}))

    navidrome.rescan_after_write(settings, 0)  # nothing changed: nothing asked, nothing said
    assert _all(engine) == []
    navidrome.rescan_after_write(settings, 3)
    navidrome.rescan_after_write(settings, 1)
    navidrome.ping(settings)  # the owner's own test in Settings: seen there, not reported
    [note] = _all(engine)
    assert note.kind == "problem" and note.summary == "Navidrome didn't answer"
    assert "Can't reach Navidrome" in note.message and note.url == "/settings#navidrome"

    answer["result"] = navidrome.Result(True, "OK")
    navidrome.rescan_after_write(settings, 1)
    navidrome.rescan_after_write(settings, 1)
    assert [n.summary for n in _all(engine)] == [
        "Navidrome didn't answer",
        "Navidrome answers again",
    ]


def test_navidrome_scan_check_before_renaming_reports_too(engine, settings, monkeypatch):
    from app import navidrome

    monkeypatch.setattr(settings, "navidrome_url", "http://192.168.1.10:4533")
    monkeypatch.setattr(settings, "navidrome_user", "admin")
    monkeypatch.setattr(settings, "navidrome_password", "secret")
    failed = navidrome.Result(False, "Navidrome answered with error 502. Is the address right?")
    monkeypatch.setattr(navidrome, "_call", lambda *args, **kwargs: (failed, {}))
    assert not navidrome.scanned_since(settings, 0).ok
    [note] = _all(engine)
    assert "before renaming" in note.message and "error 502" in note.message


# --- Online sources: a key rejected, or a source that keeps failing ---------------------------


class _Source:
    name, label = "discogs", "Discogs"


def test_a_rejected_key_is_reported_at_once_and_only_once(engine, monkeypatch):
    from app import identify

    monkeypatch.setattr(identify, "_failures", {})
    for _ in range(3):
        identify._report(
            engine, _Source(), "Discogs refused the request: check DISCOGS_TOKEN", True
        )
    [note] = _all(engine)
    assert note.summary == "Discogs refused Tagwerk's key" and note.kind == "problem"
    assert "check DISCOGS_TOKEN" in note.message and note.url == "/settings#online"
    identify._report(engine, _Source(), None, False)
    assert _all(engine)[-1].summary == "Discogs answers again"


def test_a_source_that_keeps_failing_is_reported_after_several_failures(engine, monkeypatch):
    from app import identify

    monkeypatch.setattr(identify, "_failures", {})
    for _ in range(identify.FAILING_AFTER - 1):
        identify._report(engine, _Source(), "Can't reach Discogs (timed out)", False)
    identify._report(engine, _Source(), None, False)  # one answer in between: counting restarts
    for _ in range(identify.FAILING_AFTER - 1):
        identify._report(engine, _Source(), "Can't reach Discogs (timed out)", False)
    assert _all(engine) == []
    for _ in range(3):
        identify._report(engine, _Source(), "Can't reach Discogs (timed out)", False)
    [note] = _all(engine)
    assert note.summary == "Discogs keeps failing" and "timed out" in note.message


def test_online_problems_switched_off_write_nothing(engine, monkeypatch):
    from app import identify

    monkeypatch.setattr(identify, "_failures", {})
    _switch(engine, online=False)
    identify._report(engine, _Source(), "Discogs refused the request", True)
    identify._report(engine, _Source(), None, False)
    assert _all(engine) == []


# --- Automatic imports and long jobs (both off by default) -----------------------------------


def test_automatic_imports_write_one_entry_with_a_link_to_the_history(client, engine, settings):
    import os
    import shutil
    import time

    from app.jobs import analysis_job, inbox_job
    from tests.conftest import FIXTURES

    root = settings.import_dir
    root.mkdir()
    shutil.copy(FIXTURES / "tagged.mp3", root / "complete.mp3")
    old = time.time() - 600
    os.utime(root / "complete.mp3", (old, old))
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    analysis_job.wait(60)  # automatic import waits for BPM and key from the audio

    prefs = client.get("/api/settings").json() | {"automation": "auto"}
    client.put("/api/settings", json=prefs)
    _switch(engine, auto_import=True)
    client.post("/api/inbox/scan")
    inbox_job.wait(30)
    assert client.get("/api/inbox").json() == []
    [note] = _all(engine)
    assert note.summary == "Inbox: 1 track imported automatically" and note.kind == "done"
    assert note.url.startswith("/changes/history/") and "complete.mp3" in note.message
    assert client.get(note.url).status_code == 200


def test_automatic_imports_switched_off_or_empty_write_nothing(engine):
    from app.changes import WriteProgress
    from app.jobs import report_auto_import

    assert not report_auto_import(engine, WriteProgress(action="import", written=2))  # off
    _switch(engine, auto_import=True)
    assert not report_auto_import(engine, WriteProgress(action="import", written=0))
    assert _all(engine) == []


def test_long_jobs_write_one_entry_when_many_tracks_were_done(engine, settings):
    from app.jobs import (
        LONG_JOB,
        AnalysisProgress,
        IdentifyProgress,
        report_analysis,
        report_lookups,
    )

    assert not report_analysis(engine, AnalysisProgress(library=LONG_JOB))  # off by default
    _switch(engine, long_jobs=True)
    assert not report_analysis(engine, AnalysisProgress(library=LONG_JOB - 1))  # a few: no
    assert not report_lookups(engine, IdentifyProgress(library=3))
    assert report_analysis(engine, AnalysisProgress(library=230, failed=2))
    assert report_analysis(engine, AnalysisProgress(library=40, loudness=40))
    assert report_lookups(engine, IdentifyProgress(library=120))
    assert [(n.summary, n.source, n.url) for n in _all(engine)] == [
        ("BPM and key analysed for 230 tracks", "Audio analysis", "/changes"),
        ("Loudness measured for 40 tracks", "Audio analysis", "/replaygain"),
        ("Looked up 120 tracks online", "Online lookup", "/changes"),
    ]
    assert _all(engine)[0].message == (
        "230 tracks analysed. No new values to review. 2 files couldn't be analysed."
    )


def test_analysing_the_whole_library_writes_one_entry(engine, settings):
    """The fixture library has 10 tracks: "Analyse all" is one job run, one notification."""
    from app.jobs import analysis_job, scan_job
    from app.models import Track

    _switch(engine, long_jobs=True)
    scan_job.start(settings)
    scan_job.wait(30)
    with Session(engine) as session:
        ids = list(session.exec(select(Track.id).where(Track.error.is_(None))))
    analysis_job.start(settings, ids, library=True)
    analysis_job.wait(60)
    [note] = _all(engine)
    assert note.summary == f"BPM and key analysed for {len(ids)} tracks"


# --- The bell, the menu, the card and the page ------------------------------------------------


def _seed(engine) -> list[Notification]:
    notifications.notify("inbox_trash", "needs_you", "Inbox trash: 2 files will be removed",
                         "• a.mp3\n• b.mp3", "Inbox trash", "/inbox#trash")  # fmt: skip
    notifications.notify("navidrome", "problem", "Navidrome didn't answer", "Connection refused.",
                         "Navidrome", "/settings#navidrome")  # fmt: skip
    return _all(engine)


def test_the_bell_counts_unread_and_the_menu_shows_summaries(client, engine):
    trash_note, navidrome_note = _seed(engine)
    home = client.get("/").text
    assert home.count(" data-bell ") == 2  # side menu and phone bar
    assert 'id="bell-count-side" data-count="2"><span class="count-badge">2<' in home
    # No menu entry: the page opens only through "All" in the bell's menu.
    assert 'href="/notifications"' not in home

    menu = client.get("/partials/notifications/menu").text
    assert menu.index("Navidrome didn&#39;t answer") < menu.index(
        "Inbox trash: 2 files"
    )  # newest first
    assert "Connection refused" not in menu  # summaries only
    assert "2 new" in menu and "Mark all read" in menu
    assert f'href="/notifications?open={navidrome_note.id}"' in menu  # opens it on the page
    assert 'href="/notifications"' in menu and ">All<" in menu
    # Opening the menu or the page marks nothing as read; GET never changes anything.
    client.get("/notifications")
    client.get("/notifications", params={"open": navidrome_note.id})
    client.get(f"/api/notifications/{navidrome_note.id}")
    assert client.get("/api/notifications/count").json() == {"unread": 2, "needs_you": 1}


def test_read_ones_leave_the_menu(client, engine):
    """ADR 0043: the menu holds the unread ones; read ones stay in New on the page."""
    trash_note, navidrome_note = _seed(engine)
    menu = client.post(f"/partials/notifications/{navidrome_note.id}/read").text  # ✓
    assert "Navidrome" not in menu.split('id="bell-count-side"')[0]
    assert 'id="bell-count-side" data-count="1" hx-swap-oob="true">' in menu  # the bell follows
    assert "Navidrome didn" in client.get("/notifications").text.split('id="history"')[0]

    client.post(f"/api/notifications/{trash_note.id}/read")  # opened on the page
    menu = client.get("/partials/notifications/menu").text
    assert "Nothing new" in menu and "Mark all read" not in menu

    client.post(f"/api/notifications/{trash_note.id}/unread")
    assert "Inbox trash: 2 files" in client.get("/partials/notifications/menu").text
    menu = client.post("/partials/notifications/read-all").text
    assert "Nothing new" in menu
    assert len(client.get("/api/notifications").json()) == 2  # read, still in New
    assert client.post("/partials/notifications/999/read").status_code == 404


def test_the_menu_shows_the_newest_20(client, engine):
    for i in range(25):
        notifications.notify("navidrome", "problem", f"Problem {i}", engine=engine)
    menu = client.get("/partials/notifications/menu").text
    assert (
        menu.count('class="bell-row"') == 20 and "Problem 24" in menu and "Problem 4<" not in menu
    )
    assert ">All 25 new<" in menu


def test_nothing_new_in_an_empty_menu(client):
    assert "Nothing new" in client.get("/partials/notifications/menu").text
    assert 'class="count-badge"' not in client.get("/partials/notifications/count").text


def test_the_bell_shows_9_plus_from_10_on(client, engine):
    """ "128" would cover the bell in the side menu: from 10 on it says "9+" (the owner's
    choice, tinier than "99+"); screen readers still hear the whole number."""
    for i in range(9):
        notifications.notify("navidrome", "problem", f"Problem {i}", engine=engine)
    assert '<span class="count-badge">9<' in client.get("/partials/notifications/count").text
    for i in range(119):
        notifications.notify("navidrome", "problem", f"More {i}", engine=engine)
    count = client.get("/partials/notifications/count").text
    assert '<span aria-hidden="true">9+</span><span class="visually-hidden">128 new</span>' in count


def test_the_page_new_history_clear_and_clear_history(client, engine):
    trash_note, navidrome_note = _seed(engine)
    page = client.get("/notifications").text
    assert "Mark all as read" in page and "Clear all" in page and "Clear history" not in page
    assert "Connection refused." in page  # inside the entry, opened by a click
    assert page.count(f'data-unread="{trash_note.id}"') == 1  # opening it marks it as read
    assert " data-opened" not in page

    # Clicked in the bell's menu: the page shows it opened (its script marks it as read).
    page = client.get("/notifications", params={"open": trash_note.id}).text
    assert f'data-unread="{trash_note.id}" open data-opened>' in page

    client.post(f"/api/notifications/{trash_note.id}/read")  # what opening the entry sends
    new, history = client.get("/notifications").text.split('id="history"')
    assert "Inbox trash: 2 files" in new and "1 unread · 2" in new
    # Mark as unread: shown for the read one, waiting hidden in the unread one until opened
    assert new.count("Mark as unread") == 2 and new.count("hidden data-unread-button") == 1

    client.post(f"/notifications/{trash_note.id}/clear")
    new, history = client.get("/notifications").text.split('id="history"')
    assert "Navidrome didn" in new and "Inbox trash: 2 files" in history
    assert "Clear history" in history and "Mark as unread" not in history

    client.post("/notifications/read-all")
    assert client.get("/api/notifications/count").json()["unread"] == 0
    assert len(client.get("/api/notifications").json()) == 1  # read, still in New
    client.post("/notifications/clear-all")
    assert client.get("/api/notifications").json() == []
    assert len(client.get("/api/notifications", params={"show": "history"}).json()) == 2

    client.post("/notifications/clear-history")
    assert client.get("/api/notifications", params={"show": "history"}).json() == []
    assert "Nothing new." in client.get("/notifications").text


def test_the_api(client, engine):
    trash_note, navidrome_note = _seed(engine)
    assert [n["summary"] for n in client.get("/api/notifications").json()] == [
        "Navidrome didn't answer",
        "Inbox trash: 2 files will be removed",
    ]
    one = client.get(f"/api/notifications/{trash_note.id}").json()
    assert one["message"] == "• a.mp3\n• b.mp3" and one["read_at"] is None
    assert client.post(f"/api/notifications/{trash_note.id}/read").json()["read_at"]
    assert client.post(f"/api/notifications/{trash_note.id}/unread").json()["read_at"] is None
    assert client.post("/api/notifications/read-all").json() == {"marked": 2}
    assert client.post(f"/api/notifications/{trash_note.id}/clear").json()["cleared_at"]
    assert client.post("/api/notifications/clear-all").json() == {"cleared": 1}
    assert client.post("/api/notifications/clear-history").json() == {"removed": 2}
    assert client.get("/api/notifications/999").status_code == 404


def test_home_has_a_line_for_notifications_that_need_you(client, engine):
    from app.jobs import scan_job

    client.post("/api/scan")  # Home shows "Waiting for you" once the library has tracks
    scan_job.wait(30)
    notifications.notify("navidrome", "problem", "Navidrome didn't answer")
    assert "need you" not in client.get("/").text  # a problem alone isn't "needs you"
    _seed(engine)
    home = client.get("/").text
    assert "1 notification needs you" in home and "data-open-bell" in home
    assert 'hx-get="/partials/home/waiting" hx-trigger="every 60s"' in home


def test_homes_waiting_card_keeps_up_while_home_stays_open(client, engine):
    """The card is reloaded every minute like the bell's number, not only on a page change."""
    card = client.get("/partials/home/waiting").text
    assert 'id="home-waiting"' in card and "Nothing waiting" in card
    _seed(engine)
    card = client.get("/partials/home/waiting").text
    assert "1 notification needs you" in card and "Nothing waiting" not in card


def test_settings_switch_topics_on_and_off(client, engine):
    page = client.get("/settings").text
    assert 'id="notifications"' in page and "Long jobs finished" in page
    client.post("/settings/notifications", data={"topics": ["scan", "long_jobs"]})
    with Session(engine) as session:
        chosen = preferences.load(session).notifications
    assert {name for name, on in chosen.items() if on} == {"scan", "long_jobs"}


def test_a_failing_notification_doesnt_stop_the_job(engine, settings, monkeypatch):
    from app.jobs import scan_job

    def locked(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(notifications, "_write", locked)
    monkeypatch.setattr(notifications, "_remember", locked)
    (settings.music_dir / "broken.mp3").write_bytes(b"not really audio" * 100)
    scan_job.start(settings)
    scan_job.wait(30)
    assert scan_job.status == "done" and scan_job.progress.added == 11

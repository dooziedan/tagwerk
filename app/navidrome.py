"""Telling Navidrome to rescan after Tagwerk changed files (optional).

Uses the Subsonic API that Navidrome implements (``startScan``, ``getScanStatus``, ``ping``,
``getMusicFolders``, ``search3``).
Needs the Navidrome address and a user with admin rights, set as container variables
(NAVIDROME_URL, _USER, _PASSWORD). With several Navidrome libraries, NAVIDROME_LIBRARY names the
one Tagwerk works on; only that one is rescanned (``startScan?target=<id>:``, Navidrome 0.59+;
older versions ignore the target and scan everything). The password is only sent as a salted
token, never stored or logged by Tagwerk. Standard library only: no extra dependency.
"""

import contextlib
import hashlib
import http.client
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app import notifications
from app.config import Settings

log = logging.getLogger(__name__)

TIMEOUT = 10  # seconds


@dataclass
class Result:
    ok: bool
    message: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


last: Result | None = None  # the latest rescan or connection test, shown in Settings


def configured(settings: Settings) -> bool:
    return bool(settings.navidrome_url and settings.navidrome_user and settings.navidrome_password)


def ping(settings: Settings) -> Result:
    """Check address and login, and which library Tagwerk would rescan."""
    result, _ = _call(settings, "ping")
    if not result.ok:
        return _remember(result)
    found, error = _libraries(settings)
    if error:
        return _remember(error)
    library, error = _library(settings, found)
    if error:
        return _remember(error)
    names = ", ".join(f"“{name}”" for _, name in found)
    which = f"Rescans only “{library[1]}”." if library else "Rescans all libraries."
    return _remember(Result(True, f"Connected to Navidrome. Libraries: {names}. {which}"))


def start_scan(settings: Settings) -> Result:
    """Ask Navidrome to look for changed files (it scans in the background)."""
    library = None
    if settings.navidrome_library:
        found, error = _libraries(settings)
        if not error:
            library, error = _library(settings, found)
        if error:
            return _remember(error)
    params = {"target": f"{library[0]}:"} if library else {}  # "<id>:" = the whole library
    result, _ = _call(settings, "startScan", params)
    if result.ok:
        what = f"“{library[1]}”" if library else "the library"
        result.message = f"Navidrome is rescanning {what}."
    return _remember(result)


def rescan_after_write(settings: Settings, files_changed: int) -> None:
    """Called after an apply, import or undo: rescan if something changed. Never raises."""
    if files_changed and configured(settings):
        result = start_scan(settings)
        log.info("Navidrome rescan: %s", result.message)
        _report(result, "The rescan after Tagwerk changed files")


def _report(result: Result, what: str) -> None:
    """Notifications (ADR 0035): Navidrome failing Tagwerk's own requests is reported once, and
    once more when it works again. The Settings buttons don't report: the owner sees them."""
    if result.ok:
        notifications.solved(
            "navidrome", "navidrome", "Navidrome answers again", f"{what} worked.",
            "Navidrome", "/settings#navidrome",
        )  # fmt: skip
    else:
        notifications.problem(
            "navidrome", "navidrome", "Navidrome didn't answer",
            f"{what} failed: {result.message} Tagwerk tells you once more when Navidrome answers "
            "again.",
            "Navidrome", "/settings#navidrome",
        )  # fmt: skip


# How long renaming, converting, replacing and importing adopted tracks wait for Navidrome to
# finish a scan, and how often they ask.
SCAN_WAIT = 180  # seconds
SCAN_POLL = 2


def scan_status(settings: Settings) -> tuple[Result, bool, datetime | None]:
    """(result, scanning now, when the last scan finished) from ``getScanStatus``."""
    result, body = _call(settings, "getScanStatus")
    status = body.get("scanStatus", {})
    last_scan = None
    if status.get("lastScan"):
        with contextlib.suppress(ValueError):  # an odd date: treated as "no scan known"
            last_scan = datetime.fromisoformat(status["lastScan"].replace("Z", "+00:00"))
    return result, bool(status.get("scanning")), last_scan


def scanned_since(settings: Settings, changed_at: float, sleep=time.sleep) -> Result:
    """Make sure Navidrome has scanned a file that changed at ``changed_at`` (Unix time).

    Navidrome keeps play counts and ratings of a renamed file only if the file's tags didn't
    change in the same scan (docs: "move or rename files first, trigger a quick scan, then
    update the tags"). So before renaming: if the last scan is older than the file, start one
    and wait for it. Without Navidrome set up there is nothing to wait for.
    """
    if not configured(settings):
        return Result(True, "Navidrome isn't set up.")
    started = False
    waited = 0.0
    what = "Checking whether Navidrome scanned a track before renaming it"
    while True:
        result, scanning, last_scan = scan_status(settings)
        if not result.ok or not waited:  # it answered: once is enough to know
            _report(result, what)
        if not result.ok:
            return Result(False, f"Can't check Navidrome's scan: {result.message}")
        if not scanning and last_scan and last_scan.timestamp() >= changed_at:
            return Result(True, "Navidrome has the current file.")
        if not scanning and not started:
            result = start_scan(settings)
            _report(result, what)
            if not result.ok:
                return result
            started = True
        if waited >= SCAN_WAIT:
            return Result(False, "Navidrome is still scanning; try again in a few minutes.")
        sleep(SCAN_POLL)
        waited += SCAN_POLL


@dataclass
class Moved:
    """A file Tagwerk moved into the library, as Navidrome's search finds it."""

    title: str  # its title tag; Navidrome uses the filename without extension when there is none
    size: int  # in bytes
    suffix: str  # the extension without the dot, lower case ("mp3")


def wait_until_listed(
    settings: Settings, files: list[Moved], sleep=time.sleep
) -> tuple[Result, list[bool | None]]:
    """Let Navidrome scan files Tagwerk just moved, and check that it lists them (ADR 0046).

    A running scan would ignore Tagwerk's request, so it is waited for first; then Tagwerk
    starts its own scan and waits until it is done (``lastScan`` changes), up to SCAN_WAIT.
    Then each file is looked for with ``search3``: Navidrome's Subsonic API makes up a song's
    path from its tags, so a song with the file's title, exact size and extension stands for
    "listed at its new place" (songs whose file is gone aren't found).

    Returns (result, listed): ``result.ok`` when that scan finished; ``listed`` per file True or
    False, or None when Navidrome's search didn't answer (then the finished scan is all
    Tagwerk knows). Never raises.
    """
    unknown: list[bool | None] = [None] * len(files)
    if not configured(settings):
        return Result(False, "Navidrome isn't set up."), unknown
    what = "Waiting for Navidrome's scan before writing the tags of adopted tracks"
    started = False
    before = None  # the last scan before Tagwerk's own
    waited = 0.0  # the pauses; the clock counts the answers' time too (up to TIMEOUT each)
    since = time.monotonic()
    while True:
        result, scanning, last_scan = scan_status(settings)
        if not result.ok or not waited:  # it answered: once is enough to know
            _report(result, what)
        if not result.ok:
            return Result(False, f"Can't check Navidrome's scan: {result.message}"), unknown
        if not scanning and started and last_scan != before:
            break  # Tagwerk's scan (or one started after the files moved) is done
        if not scanning and not started:
            before = last_scan
            result = start_scan(settings)
            _report(result, what)
            if not result.ok:
                return result, unknown
            started = True
        if waited >= SCAN_WAIT or time.monotonic() - since >= SCAN_WAIT:
            late = f"Navidrome's scan didn't finish within {SCAN_WAIT // 60} minutes."
            return Result(False, late), unknown
        sleep(SCAN_POLL)
        waited += SCAN_POLL
    listed = [_listed(settings, f) for f in files]
    found = sum(1 for seen in listed if seen)
    return Result(True, f"Navidrome scanned and lists {found} of {len(files)}."), listed


def _listed(settings: Settings, moved: Moved) -> bool | None:
    """Whether Navidrome's search finds a song of this file; None if it didn't answer."""
    params = {"query": moved.title, "songCount": 200, "artistCount": 0, "albumCount": 0}
    result, body = _call(settings, "search3", params)
    if not result.ok:
        return None
    songs = body.get("searchResult3", {}).get("song", [])
    return any(
        s.get("size") == moved.size and str(s.get("suffix", "")).lower() == moved.suffix
        for s in songs
    )


def _libraries(settings: Settings) -> tuple[list[tuple[str, str]], Result | None]:
    """Navidrome's libraries as (id, name); Subsonic calls them music folders."""
    result, body = _call(settings, "getMusicFolders")
    if not result.ok:
        return [], result
    folders = body.get("musicFolders", {}).get("musicFolder", [])
    return [(str(f["id"]), f.get("name", "")) for f in folders], None


def _library(
    settings: Settings, found: list[tuple[str, str]]
) -> tuple[tuple[str, str] | None, Result | None]:
    """The library named in NAVIDROME_LIBRARY as (id, name), or None for all libraries."""
    wanted = settings.navidrome_library.strip().lower()
    if not wanted:
        return None, None
    for library_id, name in found:
        if name.strip().lower() == wanted:
            return (library_id, name), None
    names = ", ".join(f"“{name}”" for _, name in found) or "none"
    message = (
        f"Navidrome has no library called “{settings.navidrome_library}”. Its libraries: {names}."
    )
    return None, Result(False, message)


def _call(settings: Settings, endpoint: str, params: dict | None = None) -> tuple[Result, dict]:
    """One Subsonic API request: (result, Navidrome's answer)."""
    if not configured(settings):
        return Result(False, "Navidrome isn't set up (NAVIDROME_URL, _USER, _PASSWORD)."), {}
    salt = secrets.token_hex(8)
    # The Subsonic API's login scheme: md5(password + salt). The password itself isn't sent.
    token = hashlib.md5((settings.navidrome_password + salt).encode()).hexdigest()
    query = urllib.parse.urlencode(
        {
            "u": settings.navidrome_user,
            "t": token,
            "s": salt,
            "v": "1.16.1",
            "c": "tagwerk",
            "f": "json",
            **(params or {}),
        }
    )
    url = f"{settings.navidrome_url.rstrip('/')}/rest/{endpoint}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = json.load(response).get("subsonic-response", {})
    except urllib.error.HTTPError as exc:
        return Result(False, f"Navidrome answered with error {exc.code}. Is the address right?"), {}
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
        reason = getattr(exc, "reason", exc)
        return Result(
            False,
            f"Can't reach Navidrome at {settings.navidrome_url} ({reason}). Use the server's IP "
            "address (or the container name on a shared Docker network), not localhost.",
        ), {}
    except ValueError:
        return Result(False, "That address doesn't answer like Navidrome."), {}
    if body.get("status") == "ok":
        return Result(True, "OK"), body
    error = body.get("error", {})
    if error.get("code") == 40:
        return Result(False, "Navidrome rejected the user name or password."), body
    if error.get("code") == 50:
        return Result(
            False, "This Navidrome user may not start scans: it needs admin rights."
        ), body
    return Result(False, f"Navidrome said: {error.get('message', 'unknown error')}"), body


def _remember(result: Result) -> Result:
    global last
    last = result
    return result

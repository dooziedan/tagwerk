"""Telling Navidrome to rescan after Tagwerk changed files (optional).

Uses the Subsonic API that Navidrome implements (``startScan``, ``getScanStatus``, ``ping``,
``getMusicFolders``).
Needs the Navidrome address and a user with admin rights, set as container variables
(NAVIDROME_URL, _USER, _PASSWORD). With several Navidrome libraries, NAVIDROME_LIBRARY names the
one Tagwerk works on; only that one is rescanned (``startScan?target=<id>:``, Navidrome 0.59+;
older versions ignore the target and scan everything). The password is only sent as a salted
token, never stored or logged by Tagwerk. Standard library only: no extra dependency.
"""

import contextlib
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

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


# How long renaming waits for Navidrome to finish a scan, and how often it asks.
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
    while True:
        result, scanning, last_scan = scan_status(settings)
        if not result.ok:
            return Result(False, f"Can't check Navidrome's scan: {result.message}")
        if not scanning and last_scan and last_scan.timestamp() >= changed_at:
            return Result(True, "Navidrome has the current file.")
        if not scanning and not started:
            result = start_scan(settings)
            if not result.ok:
                return result
            started = True
        if waited >= SCAN_WAIT:
            return Result(False, "Navidrome is still scanning; try again in a few minutes.")
        sleep(SCAN_POLL)
        waited += SCAN_POLL


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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
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

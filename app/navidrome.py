"""Telling Navidrome to rescan after Tagwerk changed files (optional).

Uses the Subsonic API that Navidrome implements (``startScan``, ``ping``). Needs the Navidrome
address and a user with admin rights, set as container variables (NAVIDROME_URL, _USER,
_PASSWORD). The password is only sent as a salted token, never stored or logged by Tagwerk.
Standard library only: no extra dependency.
"""

import hashlib
import json
import logging
import secrets
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
    """Check address and login."""
    return _remember(_call(settings, "ping", "Connected to Navidrome."))


def start_scan(settings: Settings) -> Result:
    """Ask Navidrome to look for changed files (it scans in the background)."""
    return _remember(_call(settings, "startScan", "Navidrome is rescanning the library."))


def rescan_after_write(settings: Settings, files_changed: int) -> None:
    """Called after an apply, import or undo: rescan if something changed. Never raises."""
    if files_changed and configured(settings):
        result = start_scan(settings)
        log.info("Navidrome rescan: %s", result.message)


def _call(settings: Settings, endpoint: str, success: str) -> Result:
    if not configured(settings):
        return Result(False, "Navidrome isn't set up (NAVIDROME_URL, _USER, _PASSWORD).")
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
        }
    )
    url = f"{settings.navidrome_url.rstrip('/')}/rest/{endpoint}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            body = json.load(response).get("subsonic-response", {})
    except urllib.error.HTTPError as exc:
        return Result(False, f"Navidrome answered with error {exc.code}. Is the address right?")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return Result(
            False,
            f"Can't reach Navidrome at {settings.navidrome_url} ({reason}). Use the server's IP "
            "address (or the container name on a shared Docker network), not localhost.",
        )
    except ValueError:
        return Result(False, "That address doesn't answer like Navidrome.")
    if body.get("status") == "ok":
        return Result(True, success)
    error = body.get("error", {})
    if error.get("code") == 40:
        return Result(False, "Navidrome rejected the user name or password.")
    if error.get("code") == 50:
        return Result(False, "This Navidrome user may not start scans: it needs admin rights.")
    return Result(False, f"Navidrome said: {error.get('message', 'unknown error')}")


def _remember(result: Result) -> Result:
    global last
    last = result
    return result

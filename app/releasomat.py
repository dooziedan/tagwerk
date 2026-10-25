"""Talking to Releasomat, the owner's playlist downloader (optional, ADR 0044).

Releasomat's integration API (its ADR 0009, version 1) lives under ``/api/integration/``. Only
Tagwerk calls it, never the other way round, and nothing in Tagwerk waits for it: without
``RELEASOMAT_URL`` and ``RELEASOMAT_API_KEY`` these calls aren't made at all, and when Releasomat
doesn't answer only Adopt and Delete are off.

- The key goes only into an ``Authorization: Bearer`` header, never into a URL. Logs name the
  call and the status, never headers or the key.
- Short timeouts: 5 s for ``info`` and ``files`` (pages wait for them), 15 s for the POSTs. A
  POST is never repeated inside one call; notices are retried by the regular check.
- Every failure is a ReleasomatError with a plain-language message for the page.

Standard library only, like app/navidrome.py.
"""

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.sources.base import USER_AGENT

log = logging.getLogger(__name__)

API = 1  # the integration API version Tagwerk understands
READ_TIMEOUT = 5  # seconds: info, files
POST_TIMEOUT = 15  # seconds: adopt, returned, discarded, restored, delete
PREFIX = "/api/integration"


class ReleasomatError(Exception):
    """Releasomat can't be asked, or didn't answer as expected. ``code`` names what went wrong:
    not_set_up, unreachable, integration_off, wrong_key, too_old, too_new, bad_answer, error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Result:
    """The latest contact with Releasomat, shown in Settings."""

    ok: bool
    message: str
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


last: Result | None = None


@dataclass
class Info:
    version: str
    integration_api: int
    folder: str  # Releasomat's folder inside the library (its NAVIDROME_SUBFOLDER)


@dataclass
class Playlist:
    id: int
    name: str
    url: str  # the playlist's page in Releasomat


@dataclass
class AreaFile:
    """A file in Releasomat's folder, as Releasomat knows it."""

    id: int
    path: str  # inside the area, "/" between folders, Unicode NFC
    size: int
    downloaded_at: str | None = None
    downloader: str | None = None  # slskd or youtube
    format: str | None = None
    bitrate: int | None = None  # kbit/s
    # What the file was downloaded for: artist, title, album, duration, isrc, mbid, bpm, key.
    wanted: dict = field(default_factory=dict)
    playlists: list[Playlist] = field(default_factory=list)


@dataclass
class Answer:
    """Releasomat's answer for one file of a POST."""

    asked: str  # the path as sent
    ok: bool
    changed: bool = False  # False: it already was so (a repeated call)
    reason: str | None = None  # why not, in plain words
    id: int | None = None
    path: str | None = None
    status: str | None = None  # Releasomat's state of the file now


def configured(settings: Settings) -> bool:
    return bool(settings.releasomat_url.strip() and settings.releasomat_api_key.strip())


def info(settings: Settings) -> Info:
    body = _call(settings, "GET", "info", timeout=READ_TIMEOUT)
    try:
        return Info(str(body["version"]), int(body["integration_api"]), str(body["folder"]))
    except (KeyError, TypeError, ValueError):
        raise _bad_answer(settings) from None


def files(settings: Settings) -> tuple[str, list[AreaFile]]:
    """Releasomat's folder and the files in it now (downloaded by Releasomat, on disk)."""
    body = _call(settings, "GET", "files", timeout=READ_TIMEOUT)
    try:
        found = [
            AreaFile(
                id=int(f["id"]),
                path=str(f["path"]),
                size=int(f["size"]),
                downloaded_at=f.get("downloaded_at"),
                downloader=f.get("downloader"),
                format=f.get("format"),
                bitrate=f.get("bitrate"),
                wanted=f.get("wanted") or {},
                playlists=[
                    Playlist(int(p["id"]), str(p["name"]), str(p.get("url") or ""))
                    for p in f.get("playlists") or []
                ],
            )
            for f in body["files"]
        ]
        return str(body["folder"]), found
    except (KeyError, TypeError, ValueError):
        raise _bad_answer(settings) from None


# Pages show Releasomat's playlists and the source's BPM and key; they ask at most once a minute
# (an answer that failed: once every 10 s), so paging and tabs don't wait for Releasomat.
KEEP_FILES = 60  # seconds
KEEP_FAILURE = 10
_files_cache: tuple[float, str, tuple | ReleasomatError] | None = None


def files_cached(settings: Settings) -> tuple[str, list[AreaFile]]:
    """files(), kept for a minute. Raises ReleasomatError like files()."""
    global _files_cache
    address = settings.releasomat_url.strip()
    now = time.monotonic()
    if _files_cache and _files_cache[1] == address:
        at, _, kept = _files_cache
        keep = KEEP_FAILURE if isinstance(kept, ReleasomatError) else KEEP_FILES
        if now - at < keep:
            if isinstance(kept, ReleasomatError):
                raise kept
            return kept
    try:
        found = files(settings)
    except ReleasomatError as exc:
        _files_cache = (now, address, exc)
        raise
    _files_cache = (now, address, found)
    return found


def forget_files() -> None:
    """After Adopt or Delete: the next page asks Releasomat again."""
    global _files_cache
    _files_cache = None


def adopt(settings: Settings, refs: list[dict]) -> list[Answer]:
    """The owner adopts these files: Releasomat leaves them alone from now on. ``refs``:
    ``{"path", "size", "id"?}`` each."""
    return _post(settings, "adopt", refs)


def returned(settings: Settings, refs: list[dict], why: str) -> list[Answer]:
    """Adopted files are back at their old path: ``why`` is move_failed or given_back."""
    return _post(settings, "returned", refs, why=why)


def discarded(settings: Settings, refs: list[dict]) -> list[Answer]:
    """Adopted files the owner threw away in the inbox: Releasomat marks them Don't like."""
    return _post(settings, "discarded", refs)


def restored(settings: Settings, refs: list[dict]) -> list[Answer]:
    """Undo of discarded(): the files came back from the inbox trash."""
    return _post(settings, "restored", refs)


def delete(settings: Settings, refs: list[dict]) -> list[Answer]:
    """The owner's Delete on the Releasomat page: Releasomat deletes each file itself (only
    files it downloaded, only in its folder) and marks it Don't like. Needs each size."""
    return _post(settings, "delete", refs)


def remember(result: Result) -> Result:
    global last
    last = result
    return result


def _post(settings: Settings, call: str, refs: list[dict], **extra) -> list[Answer]:
    sent = [{k: v for k, v in ref.items() if k in ("path", "size", "id") and v is not None}
            for ref in refs]  # fmt: skip
    body = _call(settings, "POST", call, {"files": sent, **extra}, timeout=POST_TIMEOUT)
    try:
        answers = [
            Answer(
                asked=str(a["asked"]),
                ok=bool(a["ok"]),
                changed=bool(a.get("changed")),
                reason=a.get("reason"),
                id=a.get("id"),
                path=a.get("path"),
                status=a.get("status"),
            )
            for a in body["files"]
        ]
    except (KeyError, TypeError, ValueError):
        raise _bad_answer(settings) from None
    if len(answers) != len(sent):
        raise _bad_answer(settings)
    return answers


def _call(settings: Settings, method: str, call: str, body: dict | None = None, *,
          timeout: float) -> dict:  # fmt: skip
    """One request to the integration API: Releasomat's answer as a dict."""
    if not configured(settings):
        raise ReleasomatError(
            "not_set_up", "Releasomat isn't set up (RELEASOMAT_URL and RELEASOMAT_API_KEY)."
        )
    address = settings.releasomat_url.strip().rstrip("/")
    request = urllib.request.Request(
        f"{address}{PREFIX}/{call}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {settings.releasomat_api_key.strip()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = json.load(response)
            log.info("Releasomat %s %s: %s", method, call, response.status)
    except urllib.error.HTTPError as exc:
        log.info("Releasomat %s %s: %s", method, call, exc.code)
        raise _http_error(settings, exc) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log.info("Releasomat %s %s: no answer", method, call)
        reason = getattr(exc, "reason", exc)
        raise ReleasomatError(
            "unreachable",
            f"Releasomat didn't answer at {address} ({reason}). Use the server's IP address (or "
            "the container name on a shared Docker network), not localhost.",
        ) from None
    except ValueError:
        raise _bad_answer(settings) from None
    if not isinstance(answer, dict):
        raise _bad_answer(settings)
    version = answer.get("integration_api")
    if isinstance(version, int) and version > API:
        raise ReleasomatError(
            "too_new",
            f"This Releasomat speaks a newer integration (version {version}) than this Tagwerk "
            f"(version {API}): update Tagwerk.",
        )
    return answer


def _http_error(settings: Settings, exc: urllib.error.HTTPError) -> ReleasomatError:
    """Releasomat's error answer in plain words."""
    try:
        body = json.loads(exc.read() or b"{}")
    except (ValueError, OSError):
        body = {}
    body = body if isinstance(body, dict) else {}
    code = body.get("error")
    if exc.code == 403 and code == "integration_off":
        return ReleasomatError(
            "integration_off",
            "Releasomat's integration for Tagwerk is off: set a key in Releasomat (Settings → "
            "Tagwerk) and the same one as RELEASOMAT_API_KEY here.",
        )
    if exc.code == 401:
        return ReleasomatError(
            "wrong_key",
            "Releasomat rejected the key: RELEASOMAT_API_KEY must be the key from Releasomat's "
            "Settings → Tagwerk.",
        )
    if exc.code == 404 and code in (None, "not_found") and "integration_api" not in body:
        return ReleasomatError(
            "too_old",
            "This Releasomat has no integration for Tagwerk yet (or the address isn't "
            "Releasomat's): update Releasomat.",
        )
    message = body.get("message") or f"error {exc.code}"
    return ReleasomatError("error", f"Releasomat answered: {message}")


def _bad_answer(settings: Settings) -> ReleasomatError:
    return ReleasomatError(
        "bad_answer",
        f"{settings.releasomat_url.strip()} doesn't answer like Releasomat. Is the address right?",
    )

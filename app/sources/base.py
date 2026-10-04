"""The shared interface of online metadata sources, and polite HTTP for all of them.

A source gets a ``Query`` (what Tagwerk knows about a track) and returns ``Candidate``s: what
it found, as values for Tagwerk's editable fields, plus a link and maybe a cover URL. Scoring
how well a candidate matches and combining sources is app/identify.py's job, so every source
stays a thin translation of one web API.

HTTP: standard library only, a clear User-Agent (MusicBrainz and Discogs require one), a
timeout, and a minimum gap between requests per source (each API's rate limit).
"""

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from app import __version__
from app.config import Settings

log = logging.getLogger(__name__)

# Where a featured artist starts: "A feat. B", "A ft. B", "A; B". Not "&": "Above & Beyond".
_MORE_ARTISTS = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+|\s*;\s*", re.I)
_FEATURING = re.compile(r"\s*[(\[](?:feat\.?|ft\.?|featuring)\s[^)\]]*[)\]]", re.I)

USER_AGENT = f"Tagwerk/{__version__} ( https://github.com/dooziedan/tagwerk )"
TIMEOUT = 15  # seconds


@dataclass
class Query:
    artist: str | None
    title: str | None
    duration: float | None  # seconds
    path: Path | None = None  # the audio file, for fingerprinting

    def key(self) -> str:
        """What was asked, to notice when the owner changed artist or title."""
        return json.dumps([self.artist, self.title, round(self.duration or 0, 1)])

    @property
    def search_artist(self) -> str:
        """The main artist for searching: "Sub Focus feat. Kele" -> "Sub Focus"."""
        return _MORE_ARTISTS.split(self.artist or "", maxsplit=1)[0].strip()

    @property
    def search_title(self) -> str:
        """The title without featured artists: "Rio (feat. Digital Farm Animals)" -> "Rio"."""
        return _FEATURING.sub("", self.title or "").strip()


@dataclass
class Candidate:
    source: str
    values: dict[str, str]  # editable field -> value, e.g. {"label": "Catch & Release"}
    url: str = ""  # the release/track page at the source
    cover_url: str = ""
    duration: float | None = None  # seconds
    score: float = 0.0  # how well it matches the track, 0..1 (set by app/identify.py)
    fingerprint_score: float | None = None  # AcoustID only: how alike the audio is
    cover_image: str | None = None  # the cover, once downloaded (an ImageStore id)
    why: str = ""  # the score in words, for the review page (app/identify.py, explain())

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Candidate":
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class SourceError(Exception):
    """A source couldn't be asked (network, key, rate limit); the message says why."""


class Source:
    """One online source. Subclasses set ``name``/``label``/``gap`` and implement lookup()."""

    name = ""
    label = ""
    gap = 1.0  # seconds between requests (the API's rate limit)
    needs = ""  # what the owner must set up, e.g. "DISCOGS_TOKEN"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def configured(self) -> bool:
        return True

    def lookup(self, query: Query) -> list[Candidate]:
        raise NotImplementedError

    # --- HTTP -------------------------------------------------------------------------------

    _last: dict[str, float] = {}
    _lock = threading.Lock()

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict:
        """GET a JSON document, waiting first if this source was asked too recently."""
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        with Source._lock:
            wait = Source._last.get(self.name, 0) + self.gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            Source._last[self.name] = time.monotonic()
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise SourceError(f"{self.label} refused the request: check {self.needs}") from None
            if exc.code in (429, 503):
                raise SourceError(f"{self.label} is busy (rate limit); tried again later") from None
            raise SourceError(f"{self.label} answered with error {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceError(f"Can't reach {self.label} ({getattr(exc, 'reason', exc)})") from None
        except ValueError:
            raise SourceError(f"{self.label} sent something that isn't JSON") from None


def year_or_date(text: str | None) -> str | None:
    """ "2018-07-13T12:00:00Z" -> "2018-07-13"; "2018" stays; nonsense -> None."""
    text = (text or "")[:10]
    return text if text[:4].isdigit() else None

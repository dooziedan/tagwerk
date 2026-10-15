"""User preferences, stored in the database (so they live in /config, the same on every device).

Not to be confused with ``app.config``, which holds the container's environment settings.
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields
from functools import cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, available_timezones

from fastapi import Depends
from sqlmodel import Session, select

from app import tempo
from app.db import SessionDep
from app.keys import NOTATIONS
from app.models import AppSetting
from app.topics import TOPICS

# The night-sky look (ADR 0021): full effects, or lighter ones for weak devices.
EFFECTS = {
    "full": "Full",
    "light": "Lighter",
}

# Where imported tracks go (only folders: filenames never change on import).
LAYOUTS = {
    "genre": "Genre folders",
    "artist": "Artist folders",
    "date": "Date added",
    "custom": "Own pattern",
}
# How independently Tagwerk handles the inbox (ADR 0007).
AUTOMATIONS = {
    "ask": "Always ask",
    "auto": "Import complete tracks automatically",
}

# Messages that explain a feature until the owner presses "Don't show again" (macros.html →
# hint). The key is what Preferences.hidden_hints stores.
HINTS = {
    "secret": "Secret tracks: the import folder's Secret folder for edits and bootlegs",
}

KeyNotation = Literal["camelot", "openkey", "musical"]
Effects = Literal["full", "light"]


@dataclass
class Preferences:
    key_notation: KeyNotation = "camelot"
    # Look (docs/design.md): "light" turns off blur, star drift and glows for weak devices.
    # (Old databases may still hold "style", "appearance", "mode" or "show_musicbrainz" rows:
    # load() ignores unknown keys.)
    effects: Effects = "full"
    # Settings → General: the owner's time zone for dates Tagwerk writes into notifications
    # ("removed for good on 14 Oct"), e.g. "Europe/Berlin". Empty: the container's (TZ).
    time_zone: str = ""
    # Set once the owner confirmed having a backup, before the very first write to files.
    backup_confirmed: bool = False
    # The setup wizard was completed (or skipped); until then the start page leads there.
    setup_done: bool = False

    # Import (wizard step 3/4, Settings → Import)
    folder_layout: str = "genre"
    folder_pattern: str = "{genre}"  # for the "custom" layout; folders only
    genre_folders: list[str] = field(default_factory=list)  # empty: the existing folders
    # Main genres the owner keeps in _Unsorted: no new folder is proposed for them.
    kept_unsorted: list[str] = field(default_factory=list)
    automation: str = "ask"
    # Remove Traktor's private data (PRIV:TRAKTOR4) from files while importing (ADR 0016).
    remove_traktor_on_import: bool = False
    # Inbox files that sound clearly better than their library copy replace it on their own
    # (the old file goes to the library trash, ADR 0037). Off: the owner presses Replace.
    replace_automatically: bool = False
    # The genre map (app/genres.py) as plain text; empty: the built-in one.
    genre_map: str = ""
    # Settings → BPM ranges: genre -> [low, high], its usual tempo (ADR 0042); None: the
    # built-in ranges (tempo.DEFAULT_RANGES), which keep up with updates.
    bpm_ranges: dict[str, list[float]] | None = None

    # Online identification (Settings → Online lookups, app/identify.py): which sources to ask.
    online_sources: list[str] = field(
        default_factory=lambda: [
            "acoustid",
            "musicbrainz",
            "discogs",
            "beatport",
            "deezer",
            "itunes",
        ]
    )

    # Final tracks (wizard step 5, Settings → Final tracks): rename when marked final.
    rename_on_final: bool = False
    filename_pattern: str = "{artist} - {title}"

    # Settings → Notifications: which topics may write notifications (app/notifications.py).
    # A topic missing here (e.g. added by a newer version) gets its default.
    notifications: dict[str, bool] = field(
        default_factory=lambda: {name: topic.on for name, topic in TOPICS.items()}
    )

    # Messages the owner chose not to see again (keys of HINTS).
    hidden_hints: list[str] = field(default_factory=list)


def load(session: Session) -> Preferences:
    stored = {row.key: json.loads(row.value) for row in session.exec(select(AppSetting))}
    prefs = Preferences()
    for f in fields(Preferences):
        if f.name in stored:
            setattr(prefs, f.name, stored[f.name])
    return _validated(prefs)


def save(session: Session, prefs: Preferences) -> Preferences:
    prefs = _validated(prefs)
    for name, value in asdict(prefs).items():
        session.merge(AppSetting(key=name, value=json.dumps(value)))
    session.commit()
    return prefs


def _validated(prefs: Preferences) -> Preferences:
    """Fall back to defaults for unknown values (e.g. from a newer or older version)."""
    default = Preferences()
    if prefs.key_notation not in NOTATIONS:
        prefs.key_notation = default.key_notation
    prefs.backup_confirmed = bool(prefs.backup_confirmed)
    if prefs.effects not in EFFECTS:
        prefs.effects = default.effects
    if prefs.time_zone not in time_zones():
        prefs.time_zone = default.time_zone
    for flag in ("setup_done", "rename_on_final", "replace_automatically"):
        setattr(prefs, flag, bool(getattr(prefs, flag)))
    if prefs.folder_layout not in LAYOUTS:
        prefs.folder_layout = default.folder_layout
    if prefs.automation not in AUTOMATIONS:
        prefs.automation = default.automation
    for names in ("genre_folders", "kept_unsorted", "online_sources"):
        value = getattr(prefs, names)
        value = value if isinstance(value, list) else []
        setattr(prefs, names, [str(g).strip() for g in value if str(g).strip()])
    for text in ("folder_pattern", "filename_pattern", "genre_map"):
        setattr(prefs, text, str(getattr(prefs, text) or ""))
    prefs.genre_map, prefs.bpm_ranges = _ranges_moved(prefs.genre_map, prefs.bpm_ranges)
    prefs.folder_pattern = prefs.folder_pattern.strip() or default.folder_pattern
    prefs.filename_pattern = prefs.filename_pattern.strip() or default.filename_pattern
    chosen = prefs.notifications if isinstance(prefs.notifications, dict) else {}
    prefs.notifications = {name: bool(chosen.get(name, topic.on)) for name, topic in TOPICS.items()}
    hidden = prefs.hidden_hints if isinstance(prefs.hidden_hints, list) else []
    prefs.hidden_hints = [key for key in HINTS if key in hidden]
    return prefs


def _ranges_moved(text: str, ranges) -> tuple[str, dict[str, list[float]] | None]:
    """BPM ranges are their own setting since 0.27 (ADR 0042). A genre map saved earlier may
    hold tempo lines ("Drum & Bass: 160-185 BPM"): they move to the ranges. Without own ranges
    they become the ranges, as the map's tempo lines were all of them; else they're added."""
    text, moved = tempo.split_ranges(text)
    if moved:
        own = tempo.ranges_of(tempo.clean_ranges(ranges))
        ranges = moved if ranges is None else {**own, **moved}
    cleaned = tempo.clean_ranges(ranges)
    return text, None if cleaned is None else {name: list(pair) for name, pair in cleaned.items()}


@cache
def time_zones() -> list[str]:
    """The time zones to choose from (Settings → General): "Europe/Berlin", …, and "UTC"."""
    old_names = ("Etc/", "SystemV/", "US/", "posix/", "right/")
    zones = (z for z in available_timezones() if "/" in z and not z.startswith(old_names))
    return [*sorted(zones), "UTC"]


def container_zone() -> str:
    """The container's time zone (TZ; Unraid sets it for every container), used when the
    owner didn't choose one."""
    return os.environ.get("TZ") or "UTC"


def zone(prefs: Preferences) -> ZoneInfo | None:
    """The owner's time zone; None means the container's (``datetime.astimezone(None)``)."""
    return ZoneInfo(prefs.time_zone) if prefs.time_zone else None


def get_preferences(session: SessionDep) -> Preferences:
    return load(session)


PreferencesDep = Annotated[Preferences, Depends(get_preferences)]

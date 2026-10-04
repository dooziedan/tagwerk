"""User preferences, stored in the database (so they live in /config, the same on every device).

Not to be confused with ``app.config``, which holds the container's environment settings.
"""

import json
from dataclasses import asdict, dataclass, fields
from typing import Annotated, Literal

from fastapi import Depends
from sqlmodel import Session, select

from app.db import SessionDep
from app.keys import NOTATIONS
from app.models import AppSetting

MODES = {
    "dj": "DJ",
    "collector": "Collector",
}

STYLES = {
    "calm": "Calm",
    "pop": "Pop",
}
APPEARANCES = {
    "system": "Follow system",
    "light": "Light",
    "dark": "Dark",
}

Mode = Literal["dj", "collector"]
KeyNotation = Literal["camelot", "openkey", "musical"]
Style = Literal["calm", "pop"]
Appearance = Literal["system", "light", "dark"]


@dataclass
class Preferences:
    # DJ: BPM, key, label, quality. Collector: albums, years, covers, lyrics.
    mode: Mode = "collector"
    key_notation: KeyNotation = "camelot"
    # MusicBrainz IDs are irrelevant for edits, bootlegs and promos, so they're opt-in.
    show_musicbrainz: bool = False
    # Look (docs/design.md): Calm = one accent colour, Pop = the full palette.
    style: Style = "calm"
    appearance: Appearance = "system"
    # Set once the owner confirmed having a backup, before the very first write to files.
    backup_confirmed: bool = False


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
    if prefs.mode not in MODES:
        prefs.mode = default.mode
    if prefs.key_notation not in NOTATIONS:
        prefs.key_notation = default.key_notation
    prefs.show_musicbrainz = bool(prefs.show_musicbrainz)
    prefs.backup_confirmed = bool(prefs.backup_confirmed)
    if prefs.style not in STYLES:
        prefs.style = default.style
    if prefs.appearance not in APPEARANCES:
        prefs.appearance = default.appearance
    return prefs


def get_preferences(session: SessionDep) -> Preferences:
    return load(session)


PreferencesDep = Annotated[Preferences, Depends(get_preferences)]

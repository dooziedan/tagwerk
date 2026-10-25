"""Notification topics: the switches in Settings → Notifications (ADR 0035).

Their own module because both app.notifications (writes only switched-on topics) and
app.preferences (stores the switches) need them.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    label: str  # Settings → Notifications
    about: str  # what it reports, in a few words (Settings)
    on: bool  # switched on in a fresh install: only what needs the owner or could lose data


# The switches. A later feature that reports something adds its own topic here.
TOPICS = {
    "inbox_trash": Topic(
        "Inbox trash",
        "Deleted inbox files will be removed for good: announced 3 days before, with a link to "
        "restore them.",
        True,
    ),
    "inbox_help": Topic(
        "Inbox needs you",
        "More inbox tracks need your help (only when the number goes up).",
        True,
    ),
    "scan": Topic(
        "Scan problems",
        "A scan was skipped because the music folder looked empty, or files couldn't be read.",
        True,
    ),
    "navidrome": Topic(
        "Navidrome",
        "Navidrome didn't answer a rescan, or the check before renaming a final track.",
        True,
    ),
    "online": Topic(
        "Online sources",
        "A source rejected its key or keeps failing.",
        True,
    ),
    "auto_import": Topic(
        "Automatic imports",
        "Inbox tracks imported on their own (automatic mode), with a link to the History.",
        False,
    ),
    "auto_upgrade": Topic(
        "Better copies replaced",
        "Library tracks replaced on their own by better-sounding inbox files (automatic "
        "replacing), with a link to the History.",
        False,
    ),
    "releasomat": Topic(
        "Releasomat",
        "Tracks that left the library because Releasomat's folder is kept out (once). Only "
        "shown when Releasomat is set up.",
        True,
    ),
    "long_jobs": Topic(
        "Long jobs finished",
        "Audio analysis or online lookups you started for many tracks.",
        False,
    ),
}

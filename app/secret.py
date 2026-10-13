"""Secret tracks: unofficial edits and bootlegs the owner marked (ADR 0036).

An edit or bootleg shares artist, title and much of its sound with the original release, so
online sources would find the original and suggest its label, cover and IDs. And bootlegs
rarely have official artwork. So a secret track:

- is **never looked up online**: no source is asked about it, not even AcoustID with the audio.
  What was found online before is forgotten when it is marked;
- is **complete without a cover** (set-ready, Final check, automatic import, app/library.py).

The mark lives only in Tagwerk's database (``secrettrack``, ``secretinboxtrack``), never as a
tag, like the final mark. Inbox files in the import folder's ``Secret`` folder are marked when
they are first found, before any lookup. The mark moves with a track into the library on import,
and back into the inbox when the import is undone.

Everything that runs on the server (BPM and key from the audio, loudness and ReplayGain, Fix IDs,
mix names, duplicates) treats secret tracks like any other.
"""

from pathlib import PurePosixPath

from sqlalchemy import delete
from sqlmodel import Session, col, select

from app.models import (
    LibraryLookup,
    OnlineLookup,
    SecretInboxTrack,
    SecretTrack,
)

# Files in this folder of the import folder (any capitals, subfolders too) arrive as secret.
FOLDER = "Secret"


def _table(inbox: bool) -> type[SecretTrack] | type[SecretInboxTrack]:
    return SecretInboxTrack if inbox else SecretTrack


def in_secret_folder(path: str) -> bool:
    """True for an inbox path (relative to IMPORT_DIR) inside the Secret folder."""
    parts = PurePosixPath(path).parts
    return len(parts) > 1 and parts[0].casefold() == FOLDER.casefold()


def is_secret(session: Session, track_id: int, inbox: bool = False) -> bool:
    """Asks the database each time: a lookup checks again while it runs."""
    table = _table(inbox)
    found = session.exec(select(table.track_id).where(table.track_id == track_id)).first()
    return found is not None


def secret_ids(session: Session, track_ids: list[int], inbox: bool = False) -> set[int]:
    """Which of these tracks are secret."""
    table = _table(inbox)
    found: set[int] = set()
    for start in range(0, len(track_ids), 500):  # SQLite limits the number of parameters
        part = track_ids[start : start + 500]
        found.update(session.exec(select(table.track_id).where(col(table.track_id).in_(part))))
    return found


def mark(session: Session, track_ids: list[int], inbox: bool = False) -> int:
    """Mark tracks as secret and forget what online sources found for them. Returns how many
    were newly marked (already secret ones are left as they are).

    Library tracks' BPM and key are decided again by the caller (analysis.refresh): without
    the online hints the audio decides on its own."""
    table = _table(inbox)
    already = secret_ids(session, track_ids, inbox)
    new = [i for i in dict.fromkeys(track_ids) if i not in already]
    for track_id in new:
        session.add(table(track_id=track_id))
    lookups = OnlineLookup if inbox else LibraryLookup
    for start in range(0, len(new), 500):
        part = new[start : start + 500]
        session.exec(delete(lookups).where(col(lookups.track_id).in_(part)))
    session.commit()
    return len(new)


def unmark(session: Session, track_ids: list[int], inbox: bool = False) -> int:
    """Remove the secret mark. Returns how many tracks had it."""
    table = _table(inbox)
    gone = 0
    for start in range(0, len(track_ids), 500):
        part = track_ids[start : start + 500]
        gone += session.exec(delete(table).where(col(table.track_id).in_(part))).rowcount
    session.commit()
    return gone

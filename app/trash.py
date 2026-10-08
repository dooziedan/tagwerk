"""The trash: files the owner deleted, kept so they can come back.

Two trashes work the same way, each a hidden folder inside its own share:
- the **inbox trash** (``/import/.tagwerk-trash``): files deleted from the inbox; removed for good
  after KEEP_DAYS by the regular inbox check (ADR 0011);
- the **library trash** (``/music/.tagwerk-trash``): copies of duplicates the owner moved there
  from the Duplicates page; kept until the owner empties it (ADR 0023). Tagwerk never removes a
  library file on its own.

Deleting is a rename on the same share (instant, nothing is copied). Each deleted file gets its
own folder named after the time it was deleted, and keeps its path inside it:

    /import/.tagwerk-trash/20261004-213000-a1b2c3/Promos/Track.mp3

so Restore knows where it came from without a database. Scans skip hidden folders, and a
``.ndignore`` file tells Navidrome to skip the trash too.
"""

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

TRASH = ".tagwerk-trash"
KEEP_DAYS = 30
_STAMP = "%Y%m%d-%H%M%S"


class TrashError(Exception):
    """A file can't be deleted or restored (the message says why)."""


@dataclass
class Deleted:
    id: str  # the folder name inside the trash
    path: str  # where it was in the inbox, relative to IMPORT_DIR
    deleted_at: datetime
    size: int

    @property
    def removed_for_good(self) -> datetime:
        return self.deleted_at + timedelta(days=KEEP_DAYS)


def delete(root: Path, rel: str) -> str:
    """Move a file (``rel``, inside ``root``) into root's trash. Returns the trash entry's id."""
    source = _inside(root, rel)
    if not source.is_file():
        raise TrashError(f"{rel} is no longer there")
    entry = f"{datetime.now(UTC):{_STAMP}}-{uuid.uuid4().hex[:6]}"
    target = root / TRASH / entry / rel
    target.parent.mkdir(parents=True)
    (root / TRASH / ".ndignore").touch()  # Navidrome: don't show what's in here
    os.rename(source, target)
    log.info("Moved %s to the trash in %s", rel, root)
    return entry


def items(root: Path) -> list[Deleted]:
    """Everything in root's trash, newest first."""
    found = []
    trash = root / TRASH
    for folder in trash.iterdir() if trash.is_dir() else []:
        when = _deleted_at(folder.name)
        files = [p for p in folder.rglob("*") if p.is_file()]
        if when and len(files) == 1:
            rel = files[0].relative_to(folder).as_posix()
            try:
                found.append(Deleted(folder.name, rel, when, files[0].stat().st_size))
            except OSError:  # removed in the meantime
                continue
    return sorted(found, key=lambda d: d.deleted_at, reverse=True)


def restore(root: Path, entry: str) -> str:
    """Move a deleted file back to where it was. Returns its path (inside ``root``)."""
    item = next((d for d in items(root) if d.id == entry), None)
    if item is None:
        raise TrashError("That file is no longer in the trash")
    target = _inside(root, item.path)
    if target.exists():
        raise TrashError(f"{item.path} is there again; nothing was overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(root / TRASH / entry / item.path, target)
    shutil.rmtree(root / TRASH / entry)  # now empty folders only
    log.info("Restored %s from the trash in %s", item.path, root)
    return item.path


def purge(import_dir: Path, now: datetime | None = None) -> int:
    """Inbox trash only: remove files deleted more than KEEP_DAYS ago for good. Returns how many."""
    limit = (now or datetime.now(UTC)) - timedelta(days=KEEP_DAYS)
    removed = 0
    for item in items(import_dir):
        if item.deleted_at < limit:
            try:
                shutil.rmtree(import_dir / TRASH / item.id)
                removed += 1
            except OSError as exc:  # e.g. permissions: tried again on the next check
                log.warning("Could not remove %s from the inbox trash: %s", item.path, exc)
    if removed:
        log.info("Removed %d files from the inbox trash for good", removed)
    return removed


def empty(root: Path) -> int:
    """Remove everything in root's trash for good (the owner pressed "Empty trash").

    Only Tagwerk's own folders in it are touched. Returns how many files went."""
    removed = 0
    for item in items(root):
        shutil.rmtree(root / TRASH / item.id)
        removed += 1
    log.info("Emptied the trash in %s: %d files removed for good", root, removed)
    return removed


def _deleted_at(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[:15], _STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None  # not one of Tagwerk's folders: left alone


def _inside(root: Path, rel: str) -> Path:
    """The path of a file inside ``root``; refuses anything outside it (or in the trash)."""
    base = root.resolve()
    path = (base / rel).resolve()
    if not path.is_relative_to(base) or TRASH in Path(rel).parts:
        raise TrashError("Not a file in that folder")
    return path

"""The inbox trash: files the owner deleted from the inbox, kept for a while so they can return.

Deleting moves the file into a hidden folder inside the import folder, so it is a rename on the
same share (instant, nothing is copied). Each deleted file gets its own folder named after the
time it was deleted, and keeps its path inside it:

    /import/.tagwerk-trash/20261004-213000-a1b2c3/Promos/Track.mp3

so Restore knows where it came from without a database. The inbox scan skips hidden folders.
Files older than KEEP_DAYS are removed for good by the regular inbox check.
Only inbox files are ever put here: the library is never touched.
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


def delete(import_dir: Path, rel: str) -> str:
    """Move an inbox file into the trash. Returns the trash entry's id."""
    source = _inside(import_dir, rel)
    if not source.is_file():
        raise TrashError(f"{rel} is no longer in the inbox")
    entry = f"{datetime.now(UTC):{_STAMP}}-{uuid.uuid4().hex[:6]}"
    target = import_dir / TRASH / entry / rel
    target.parent.mkdir(parents=True)
    os.rename(source, target)
    log.info("Moved %s to the inbox trash", rel)
    return entry


def items(import_dir: Path) -> list[Deleted]:
    """Everything in the trash, newest first."""
    found = []
    root = import_dir / TRASH
    for folder in root.iterdir() if root.is_dir() else []:
        when = _deleted_at(folder.name)
        files = [p for p in folder.rglob("*") if p.is_file()]
        if when and len(files) == 1:
            rel = files[0].relative_to(folder).as_posix()
            try:
                found.append(Deleted(folder.name, rel, when, files[0].stat().st_size))
            except OSError:  # removed in the meantime
                continue
    return sorted(found, key=lambda d: d.deleted_at, reverse=True)


def restore(import_dir: Path, entry: str) -> str:
    """Move a deleted file back to where it was. Returns its inbox path."""
    item = next((d for d in items(import_dir) if d.id == entry), None)
    if item is None:
        raise TrashError("That file is no longer in the trash")
    target = _inside(import_dir, item.path)
    if target.exists():
        raise TrashError(f"{item.path} is in the inbox again; nothing was overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(import_dir / TRASH / entry / item.path, target)
    shutil.rmtree(import_dir / TRASH / entry)  # now empty folders only
    log.info("Restored %s from the inbox trash", item.path)
    return item.path


def purge(import_dir: Path, now: datetime | None = None) -> int:
    """Remove files deleted more than KEEP_DAYS ago for good. Returns how many."""
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


def _deleted_at(name: str) -> datetime | None:
    try:
        return datetime.strptime(name[:15], _STAMP).replace(tzinfo=UTC)
    except ValueError:
        return None  # not one of Tagwerk's folders: left alone


def _inside(import_dir: Path, rel: str) -> Path:
    """The path of an inbox file; refuses anything outside the import folder."""
    root = import_dir.resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or TRASH in Path(rel).parts:
        raise TrashError("Not a file in the inbox")
    return path

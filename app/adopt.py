"""The owner's actions on files in the Releasomat area (ADR 0044): Adopt and Delete.

**Adopt moves a file into the import inbox**, never straight into the library: identification,
BPM and key, the duplicate check and the review happen there, as for every new track.
1. Before anything changes, each file is checked: still there and as Tagwerk read it, unchanged
   for 2 minutes, Tagwerk may remove it, and its place in the inbox
   (``/import/Releasomat/<path in the area>``) is free (never overwritten).
2. **Releasomat first**: one ``adopt`` call for the files that passed. No answer or an error:
   nothing moves. From then on Releasomat leaves those paths alone and never downloads them again.
3. Then each file moves like an import (``importer.move_file``: copy under a hidden name, compare
   checksums, rename, remove the original). A failed move leaves the original where it was and
   Releasomat is told (``returned``, why ``move_failed``; kept as a notice if Releasomat is gone in
   that second). If only removing the original fails, Tagwerk removes its own fresh inbox copy,
   so the file is never in both places.
4. The file is read into the inbox list at once, and the adoption is recorded
   (``releasomatadoption``).

**Delete asks Releasomat.** Tagwerk never deletes an area file itself: it sends the file's path,
size and Releasomat's id to Releasomat's ``delete`` call, and Releasomat deletes the file with
its own owner's delete (only files it downloaded, only in its folder) and marks the track
"Don't like", so it is never downloaded again. Afterwards Tagwerk reads those paths again: a
file that is gone leaves the list, one Releasomat refused stays, with its reason.

Nothing imports this module except routes (ADR 0040, no import circles).
"""

import json
import logging
import os
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import area, preferences, releasomat
from app.changes import WriteProgress
from app.config import Settings
from app.importer import STABLE_AFTER, move_file
from app.inbox import add_file
from app.models import ReleasomatAdoption, ReleasomatFile

log = logging.getLogger(__name__)

INBOX_FOLDER = "Releasomat"  # adopted files arrive in /import/Releasomat/<path in the area>


class NotReady(Exception):
    """Delete (or Adopt) can't start now; the message says why, in plain words."""


@dataclass
class Outcome:
    """What happened to one file."""

    path: str  # relative to the area
    done: bool
    reason: str | None = None  # why not, in plain words


def ready(settings: Settings, session: Session) -> None:
    """Raises NotReady when Adopt can't start: no kept-out folder, no import folder, or
    Releasomat not set up or not answering. Checked before the job starts."""
    if area.area_dir(settings, preferences.load(session)) is None:
        raise NotReady("The Releasomat folder isn't kept out of the library.")
    import_dir = settings.import_dir
    if not import_dir.is_dir():
        raise NotReady(
            "Adopting moves tracks into the import inbox: map /import in the container "
            "template (Import Inbox). Nothing was adopted."
        )
    if not os.access(import_dir, os.W_OK | os.X_OK):
        raise NotReady(f"Tagwerk may not write into {import_dir}. Nothing was adopted.")
    if not releasomat.configured(settings):
        raise NotReady("Adopting needs Releasomat (RELEASOMAT_URL and RELEASOMAT_API_KEY).")


def adopt_files(
    engine: Engine, settings: Settings, ids: list[int], progress: WriteProgress
) -> None:
    """The owner's Adopt (a job: it shares the job lock). Fills ``progress``: ``written`` files
    adopted, ``failed`` ones with their reason in ``errors``. Raises NotReady when Releasomat
    doesn't answer: then nothing moved."""
    with Session(engine) as session:
        ready(settings, session)
        root = area.area_dir(settings, preferences.load(session))
        rows = sorted(
            session.exec(select(ReleasomatFile).where(col(ReleasomatFile.id).in_(ids))),
            key=lambda r: r.path,
        )
    progress.total = len(rows)
    try:
        _folder, known = releasomat.files(settings)  # fresh: ids, sizes and playlists now
    except releasomat.ReleasomatError as exc:
        raise NotReady(f"{exc.message} Nothing was adopted.") from None
    by_path = {unicodedata.normalize("NFC", f.path): f for f in known}

    passed = []
    for row in rows:
        problem = _cannot_adopt(settings, root, row)
        if problem:
            _failed(progress, row.path, problem)
        else:
            passed.append(row)
    if not passed:
        return
    refs = [_ref(row, by_path) for row in passed]
    try:
        answers = releasomat.adopt(settings, refs)
    except releasomat.ReleasomatError as exc:
        raise NotReady(f"{exc.message} Nothing was adopted.") from None
    releasomat.forget_files()

    moved = []
    for row, ref, answer in zip(passed, refs, answers, strict=True):
        progress.current = row.path
        if not answer.ok:
            _failed(progress, row.path, answer.reason or "Releasomat refused.")
            continue
        about = by_path.get(ref["path"])
        ref["id"] = answer.id or ref.get("id")
        inbox_path = f"{INBOX_FOLDER}/{row.path}"
        try:
            _move(root / row.path, settings.import_dir / inbox_path)
        except Exception as exc:  # the original stays where it was: Releasomat takes it back
            log.warning("Could not adopt %s: %s", row.path, exc)
            _failed(progress, row.path, f"the move failed ({exc}); the file stays in the folder")
            _record(engine, row, ref, inbox_path, about, state="returned", notice="returned")
            _send_returned(engine, settings, ref)
            continue
        _tidy(root, row.path)
        with Session(engine) as session:
            add_file(session, settings.import_dir, inbox_path)  # in the Inbox at once
            session.commit()
        _record(engine, row, ref, inbox_path, about)
        moved.append(row.path)
        progress.written += 1
        progress.processed += 1
    progress.current = ""
    if moved:
        area.sync(engine, settings, moved)  # they left the area
    log.info("Adopted %d of %d Releasomat files", progress.written, progress.total)


def _cannot_adopt(settings: Settings, root: Path, row: ReleasomatFile) -> str | None:
    """Why this file can't be adopted now (nothing changed yet), or None."""
    source = root / row.path
    try:
        stat = source.stat()
    except OSError:
        return "the file isn't there any more"
    if row.error:
        return "the file can't be read"
    if stat.st_size != row.size or stat.st_mtime != row.mtime:
        return "the file changed since Tagwerk read it: press Check again"
    if time.time() - stat.st_mtime < STABLE_AFTER:
        return "the file is still new (maybe still being copied): try again in 2 minutes"
    if not os.access(source.parent, os.W_OK | os.X_OK):
        return "Tagwerk may not remove files there: both containers need the same PUID/PGID"
    target = settings.import_dir / INBOX_FOLDER / row.path
    if target.exists():
        return f"{INBOX_FOLDER}/{row.path} is already in the inbox"
    return None


def _ref(row: ReleasomatFile, by_path: dict) -> dict:
    path = unicodedata.normalize("NFC", row.path)
    about = by_path.get(path)
    return {"path": path, "size": row.size, "id": about.id if about else None}


def _move(source: Path, target: Path) -> None:
    """Copy, verify, rename, remove the original (importer.move_file). If only removing the
    original failed, Tagwerk's own fresh copy (identical by checksum) goes again, so the file is
    never in both places."""
    try:
        move_file(source, target)
    except Exception:
        if source.exists() and target.exists():
            target.unlink()
        raise


def _tidy(root: Path, rel: str) -> None:
    """The folders the file left, if they are empty now (an artist's folder in the area)."""
    folder = (root / rel).parent
    while folder != root and folder.is_relative_to(root):
        try:
            folder.rmdir()  # only removes an empty folder
        except OSError:
            return
        folder = folder.parent


def _record(engine, row, ref, inbox_path, about, state="adopted", notice="") -> None:
    with Session(engine) as session:
        session.add(
            ReleasomatAdoption(
                area_path=row.path,
                inbox_path=inbox_path,
                releasomat_id=ref.get("id"),
                size=row.size,
                title=row.title or (about.wanted.get("title") if about else None),
                artist=row.artist or (about.wanted.get("artist") if about else None),
                playlists=json.dumps([p.name for p in about.playlists] if about else []),
                state=state,
                notice=notice,
                notice_since=datetime.now(UTC) if notice else None,
            )
        )
        session.commit()


def _send_returned(engine, settings: Settings, ref: dict) -> None:
    """Tell Releasomat a file never left (the move failed). If it can't be told now, the notice
    stays on the adoption record and is sent later (send_notices)."""
    try:
        [answer] = releasomat.returned(settings, [ref], "move_failed")
    except releasomat.ReleasomatError as exc:
        _note_error(engine, ref["path"], exc.message)
        return
    if answer.ok:
        with Session(engine) as session:
            for record in session.exec(
                select(ReleasomatAdoption).where(
                    ReleasomatAdoption.area_path == ref["path"],
                    ReleasomatAdoption.notice == "returned",
                )
            ):
                record.notice, record.notice_error = "", None
                session.add(record)
            session.commit()
    else:
        _note_error(engine, ref["path"], answer.reason or "Releasomat refused.")


def _note_error(engine, area_path: str, message: str) -> None:
    with Session(engine) as session:
        for record in session.exec(
            select(ReleasomatAdoption).where(
                ReleasomatAdoption.area_path == area_path, ReleasomatAdoption.notice != ""
            )
        ):
            record.notice_error = message
            session.add(record)
        session.commit()


def _failed(progress: WriteProgress, path: str, reason: str) -> None:
    progress.failed += 1
    progress.processed += 1
    progress.errors.append(f"{path}: {reason}")


def delete_files(engine: Engine, settings: Settings, ids: list[int]) -> list[Outcome]:
    """The owner's Delete on the Releasomat page: ask Releasomat to delete these files. Raises
    NotReady when Releasomat isn't set up or doesn't answer; then nothing changes."""
    with Session(engine) as session:
        root = area.area_dir(settings, preferences.load(session))
        if root is None:
            raise NotReady("The Releasomat folder isn't kept out of the library.")
        rows = list(session.exec(select(ReleasomatFile).where(col(ReleasomatFile.id).in_(ids))))
    if not releasomat.configured(settings):
        raise NotReady("Deleting needs Releasomat (RELEASOMAT_URL and RELEASOMAT_API_KEY).")
    try:
        _folder, known = releasomat.files_cached(settings)
    except releasomat.ReleasomatError as exc:
        raise NotReady(f"{exc.message} Nothing was deleted.") from None
    ids_by_path = {unicodedata.normalize("NFC", f.path): f.id for f in known}

    outcomes: list[Outcome] = []
    asked: list[ReleasomatFile] = []
    for row in sorted(rows, key=lambda r: r.path):
        try:
            stat = (root / row.path).stat()
        except OSError:
            outcomes.append(Outcome(row.path, False, "The file isn't there any more."))
            continue
        if stat.st_size != row.size or stat.st_mtime != row.mtime:
            outcomes.append(Outcome(row.path, False, "The file changed: press Check again."))
            continue
        asked.append(row)
    if asked:
        refs = [
            {"path": unicodedata.normalize("NFC", r.path), "size": r.size,
             "id": ids_by_path.get(unicodedata.normalize("NFC", r.path))}
            for r in asked
        ]  # fmt: skip
        try:
            answers = releasomat.delete(settings, refs)
        except releasomat.ReleasomatError as exc:
            raise NotReady(f"{exc.message} Nothing was deleted.") from None
        releasomat.forget_files()
        area.sync(engine, settings, [r.path for r in asked])  # what is gone leaves the list
        for row, answer in zip(asked, answers, strict=True):
            gone = not (root / row.path).exists()
            if answer.ok and gone:
                outcomes.append(Outcome(row.path, True))
            elif answer.ok:
                still = "Releasomat said yes, but the file is still there."
                outcomes.append(Outcome(row.path, False, still))
            else:
                outcomes.append(Outcome(row.path, False, answer.reason or "Releasomat refused."))
    done = sum(o.done for o in outcomes)
    log.info("Delete through Releasomat: %d of %d files deleted", done, len(outcomes))
    return outcomes

"""The owner's actions on files in the Releasomat area (ADR 0044): Delete, and Adopt (step 5).

**Delete asks Releasomat.** Tagwerk never deletes an area file itself: it sends the file's path,
size and Releasomat's id to Releasomat's ``delete`` call, and Releasomat deletes the file with
its own owner's delete (only files it downloaded, only in its folder) and marks the track
"Don't like", so it is never downloaded again. Afterwards Tagwerk reads those paths again: a
file that is gone leaves the list, one Releasomat refused stays, with its reason.

Nothing imports this module except routes (ADR 0040, no import circles).
"""

import logging
import unicodedata
from dataclasses import dataclass

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import area, preferences, releasomat
from app.config import Settings
from app.models import ReleasomatFile

log = logging.getLogger(__name__)


class NotReady(Exception):
    """Delete (or Adopt) can't start now; the message says why, in plain words."""


@dataclass
class Outcome:
    """What happened to one file."""

    path: str  # relative to the area
    done: bool
    reason: str | None = None  # why not, in plain words


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

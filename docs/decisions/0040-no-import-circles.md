# 0040: Modules import in one direction: no circles, not even inside functions
Date: 2026-10-13 · Status: Accepted

## Context
A knowledge graph of the code (graphify) found 17 import circles between `app/changes.py`, `app/upgrade.py`, `app/importer.py`, `app/convert.py`, `app/ids.py`, `app/analysis.py`, `app/identify.py` and `app/secret.py`. Python still ran, because each circle was broken by an import inside a function ("these import app.changes themselves"). But that hid who depends on whom, and every new feature with an undo made it worse. The causes:

- **Undo lived in `app/changes.py`.** Almost every module imports `changes` for `stage()` and `WriteProgress`, but `undo_changeset()` has to call the undo of each feature that moves files (import, better copy, AIFF, final rename, genre folder), so the bottom module reached up to the top ones.
- **Marking a track secret decided its BPM and key again** inside `secret.mark()`. That needed `analysis`, which needs `identify` (the online hints), which needs `secret`.
- Two small ones: `notifications` and `preferences` read each other (the topics and the switches), and `jobs` ran the regular checks in `reminders`, which asked `jobs` whether a job was running.

## Decision
- **Undo has its own module, `app/undo.py`,** above everything it undoes. It imports them normally; `app/changes.py` keeps staging, apply and the history.
- **`secret.mark()` only marks** and forgets the online answers. The caller decides BPM and key again (`routes/secret.py`), as it already starts the lookup after an unmark.
- **The notification topics live in `app/topics.py`,** read by `notifications` and `preferences`.
- **The every-few-minutes loop lives in `app/reminders.py`** with the checks it runs; `jobs` doesn't know about reminders.
- **A test (`tests/test_imports.py`) fails on any import circle in `app/`,** counting imports inside functions too. Imports inside functions stay allowed for other reasons (loading a heavy module only when needed), just not to hide a circle.

## Consequences
- What a module needs is at the top of the file again; the circles are gone, and no behaviour changed.
- A new feature with an undo adds its branch to `app/undo.py`, not to `app/changes.py`.
- Code that marks library tracks secret outside the route must call `analysis.refresh` itself (only tests do so today).

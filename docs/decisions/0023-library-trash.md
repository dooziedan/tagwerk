# 0023: A trash for library copies
Date: 2026-10-08 · Status: Accepted

## Context
The Duplicates page suggests which copy of a track to keep and lets the owner take tags over from the others ([ADR 0022](0022-library-duplicates.md)). Removing the other copies meant leaving Tagwerk for a file manager. The owner wants to do it on the page. Until now the rule was that Tagwerk never deletes library files; the library is the owner's master.

## Decision
- **A library trash**, the same as the inbox trash ([ADR 0011](0011-inbox-duplicates-and-trash.md)): `.tagwerk-trash/` inside the music folder. Moving a file there is a rename on the same share (instant, nothing copied); each file keeps its library path inside a folder named after the time it went, so Restore needs no database. Scans skip hidden folders, and a `.ndignore` file tells Navidrome to skip it too.
- **Only from the Duplicates page, only the owner's action, with a confirmation.** Every copy except the one to keep has **Move to trash**, so one copy always stays. Final tracks are locked and can't be trashed.
- The copy leaves the library at once: its track row goes (with its analysis and pending changes), the groups are worked out again and Navidrome is asked to rescan. **Restore** moves the file back and reads it in again (as a new track: its added date is the file's date).
- **Removed for good only when the owner presses Empty trash** (confirmed, with the number of files and their size). Unlike the inbox trash there is no automatic removal: Tagwerk never removes a library file on its own.
- Moving to the trash takes the job lock: never during a scan or a write.

## Consequences
- The trash takes space on the music share until it is emptied; the Duplicates page shows how much.
- A `.lrc` lyrics file next to a trashed copy stays where it is.
- History doesn't list trash moves: the trash itself is the record, with Restore.

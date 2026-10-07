# 0020: Tagwerk's work, and recording where values came from
Date: 2026-10-07 · Status: Accepted

## Context
The owner wants to see what Tagwerk has done for the library. The History already holds every applied change (`changeset`, `changeentry` with `{field: [old, new]}`), so most of it can be counted for the past too. What the History doesn't know is where a value came from: the owner's typing, the audio analysis, an online source, the filename, a spelling clean-up, Fix IDs or the private-data removal. A daily snapshot of the library (for trend lines) was considered and left for later.

## Decision
- **Statistics → Tagwerk's work** (`app/work.py`, `/stats#work`, `/api/stats/work`) counts only changes still in place: written without error, not undone.
  - Headline numbers: tag values written, tracks improved, imported, converted to AIFF, marked final, genre folders created. Track numbers link to their lists (new flags `tagwerk_tags`, `tagwerk_edited`, `tagwerk_imported`, `tagwerk_converted`, conditions in `app/library.py`); the others link to the History.
  - Per field: filled in (was empty), corrected (had another value), removed. MusicBrainz/Discogs IDs and private data of other programs are one row each.
  - Activity: files changed per month (24 months), one column per month.
  - Set-ready before → now (DJ mode), for library tracks Tagwerk wrote tags to and for imported tracks. "Before" is rebuilt from each field's old value at Tagwerk's first change (imported tracks: as they arrived in the inbox); the rest of the track as it is now.
  - Home shows one line: "Tagwerk has written N tag values to M tracks".
- **Sources are recorded from now on**: `pendingchange.source` and `changeentry.sources` (JSON `{field: source}`, migration 0013, both nullable). Sources: `you`, `audio`, `online`, `filename`, `clean-up`, `fix-ids`, `private-data` (`app.changes.SOURCES`). The `changes` JSON keeps its `[old, new]` shape, so nothing that reads it changes.
  - `changes.stage()` / `stage_cover()` take the source (default `you`). Saving a pending change again with the same value keeps its source, so saving the edit form doesn't turn an audio value into "you".
  - Imports take it from the review: the owner's value is `you`, a suggestion brings its own source.
  - Older entries have no source and count as "source unknown". The Changes page and the History show the source under the field name.

## Consequences
- "Where the values came from" starts empty on existing installs and fills up with new changes.
- The work numbers read the whole History on each visit to Statistics; fine for tens of thousands of changes, may need caching beyond that.
- The set-ready "before" assumes fields Tagwerk never changed were the same before; edits by other programs aren't known.

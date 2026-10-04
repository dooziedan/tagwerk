# 0006: DJ and Collector modes change the view, never the data
Date: 2026-10-04 · Status: Accepted

## Context
The owner is a DJ. For DJ work, BPM, key, label and audio quality matter, and MusicBrainz IDs mostly don't, because edits, bootlegs and promos aren't on MusicBrainz. Other people (or the owner on another day) care about albums, years, cover art and lyrics instead. One dashboard for both would either be cluttered or call half the library "incomplete" for the wrong reasons.

## Decision
- Two **modes**, *DJ* and *Collector*, switchable from the menu.
- A mode only decides **what is shown and which tags count as "missing"**. The scanner always reads and stores every field, whatever the mode.
- Mode, key notation and MusicBrainz visibility are **preferences stored in the database** (`appsetting` table in `/config`), so they're the same on every device and survive container updates.
- **Keys** are stored as written in the file plus a parsed Camelot code. The display notation (Camelot / Open Key / musical) is a preference. Files are never rewritten just to change notation.
- MusicBrainz checks are **opt-in** in both modes.

## Consequences
- Switching modes is instant and can't lose data.
- Each new feature decides per mode what to emphasize (e.g. Phase 2's edit form puts BPM/key first in DJ mode).
- Preferences are global, not per user. If logins are added later, they can become per-user without changing the data model for tracks.

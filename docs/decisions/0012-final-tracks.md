# 0012: Final tracks, and renaming only when marking final
Date: 2026-10-04 · Status: Accepted

## Context
Once a track is fully tagged and checked, the owner wants it to stay as it is: no accidental batch edit, and optionally a filename built from its tags (`Artist - Title [BPM Key]`). Renaming must not cost the play counts and ratings that Navidrome keeps for the file.

## Decision
- **Final check** page: complete tracks (title, artist, genre, BPM, key, cover; readable; no pending changes), one at a time, with **Mark as final** or **Skip**.
- The mark is stored **only in Tagwerk's database** (`finaltrack`), never as a tag. It records the file time, so a change by another program shows as *changed outside Tagwerk* (the mark stays).
- Final tracks are **locked**: edits skip them (single edits lead to the track page, batch edits say how many are skipped).
- **Renaming** happens only when *Mark as final* is pressed and renaming is switched on (wizard / Settings). The name comes from the filename pattern; folder and extension stay; a `.lrc` with the same name follows; an existing file is never overwritten. The page shows the new name before confirming.
- **Navidrome first.** Navidrome reconnects a renamed file to its play counts and ratings, but not when the file's tags changed in the same scan (its docs: rename first, scan, then change tags). So before renaming, Tagwerk asks Navidrome (`getScanStatus`) whether its last scan is newer than the file. If not, it starts a scan and waits (up to 3 minutes); if Navidrome can't confirm, nothing is renamed. After renaming, Navidrome rescans.
- **Remove final mark** asks what happens to the name: keep it, go back to the name before it was marked final, or type one (made share-safe, extension kept).
- Marking is recorded in the history; **undo** removes the mark and gives a renamed file its old name back.

## Consequences
- Marking runs as a background job, because it may wait for Navidrome.
- A file renamed by another program becomes a new track for Tagwerk's scan, and the final mark is lost (the old row disappears).
- Without Navidrome configured, there's nothing to wait for and renaming happens at once.

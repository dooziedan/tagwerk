# 0011: Duplicates in the inbox, and an inbox trash
Date: 2026-10-04 · Status: Accepted

## Context
New music often arrives twice: the same promo from two pools, a re-download, a track bought again. Until now the import only refused to overwrite a file with the same name in the same folder; any other copy went into the library as a second file. The owner wants to see such copies in the inbox and get rid of the inbox file.

## Decision
- **Detect, show, never decide.** An inbox track is a likely duplicate of a library track when it is the identical file (same size and content), has the same MusicBrainz recording ID (only trusted when every library track with that ID has the same artist and title, the inbox artist, if known, is the same, and the lengths are close: some taggers copy one ID onto a whole EP), or has the same main artist and title with lengths within 3 seconds. Titles keep the mix name (an "Extended Mix" is not the "Jus Ron Edit"); only spelling is evened out. Detection uses the values the track will have on import (the owner's, else Tagwerk's suggestion, else the file's).
- The inbox list marks such tracks **In library** (own tab); the review page compares both copies (path, format, bitrate, length, size).
- **Automatic import skips likely duplicates**: the owner decides those.
- **Deleting moves the inbox file into a trash** (`.tagwerk-trash/` inside the import folder: a rename on the same share). Each file keeps its inbox path inside a folder named after the deletion time, so restoring needs no database. The Inbox page lists *Recently deleted* with **Restore**; the regular inbox check removes files older than 30 days for good.
- **Only inbox files can be deleted.** Library files are never deleted by Tagwerk; the duplicate's library copy is never touched.

## Consequences
- A re-downloaded copy of an already imported track usually has different tags and bytes, so it is found by artist and title, not as an identical file. Tracks without title or artist (and no MusicBrainz ID) are only found when the file is identical.
- The trash takes space on the import share for up to 30 days.
- Matching edits and bootlegs by name stays deliberately strict; a miss means a second copy, which the owner can still delete later in the library.

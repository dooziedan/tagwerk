# 0022: Duplicates in the library
Date: 2026-10-08 · Status: Accepted

## Context
The inbox already marks tracks that are in the library ([ADR 0011](0011-inbox-duplicates-and-trash.md)). The library itself holds copies too: the same track bought twice, a FLAC and an MP3 of one release, a promo filed under two genres, files copied by hand. The owner wants to see them before 1.0, without Tagwerk ever deleting a library file.

## Decision
- **The same rules as the inbox**, applied to every pair of library tracks: an identical file (same size, same content), the same MusicBrainz recording ID (trusted only when every track with that ID has the same main artist and title, and the lengths are within 3 s), or the same main artist and title with the mix name, lengths within 3 s. Only small buckets are compared pairwise (same size, same ID, same name), so a library of 20,000 tracks takes about a second.
- Tracks linked directly or through another copy form one **group** (a FLAC, its MP3 and an identical copy of the MP3 are one group). Each track keeps its strongest link (identical file > recording > name) to show why it is there.
- **Stored, not computed per page**: the groups go into a `duplicatetrack` table, worked out again after every scan, apply, undo, import, conversion and once on start. The track list's *In the library more than once* filter, the number on Home and Statistics, and the Duplicates page all read it, so the numbers agree and pages stay quick.
- **The Duplicates page** shows each group's copies side by side: file and folder (with ▶), audio quality, length, size, the main tags, cover, date added and the final mark. Rows where the copies differ stand out; rows where they agree are quiet. A copy with clearly the best sound (lossless, then sample rate, bit depth, bitrate) and one with clearly the most tags get a badge. Groups can be filtered by reason; a track page links to its group.
- **Tagwerk never deletes library files.** To remove a copy, the owner deletes it in the file manager; the next scan notices. **Keep them all** remembers every pair of the group as "not duplicates" (`notduplicate` table, cascades when a track goes), so the group isn't shown again unless another copy turns up. *Show those again* forgets all such choices.

## Consequences
- The groups are as fresh as the last scan or write: a file copied in by hand appears after the next scan.
- Hashing only happens for files of the very same size, which is rare for different tracks; WAV/AIFF files of identical length are the exception and cost one read each.
- Edits and bootlegs stay matched strictly by name and length, like in the inbox: a miss means a copy stays unnoticed, never that Tagwerk acts on a wrong guess.
- "Keep them all" is stored per pair of track ids: a file that is moved outside Tagwerk becomes a new track and may show up again.

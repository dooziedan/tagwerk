# 0016: Removing private ID3 data through Changes
Date: 2026-10-05 · Status: Accepted

## Context
Programs can keep their own binary data in private ID3 frames (`PRIV:<owner>`). On the owner's library many files carry `PRIV:TRAKTOR4`: Traktor's waveform, beat grid, cue points and its own copy of the track info, tens of kilobytes per file, left by whoever analysed the file before. The owner doesn't use Traktor and wants it gone. It also used to make the Tag fields page huge (fixed in 0.8.3: raw field names no longer contain the data).

## Decision
- Removing one program's private data is a **pending change** like any edit: field `private:<owner>` (e.g. `private:TRAKTOR4`), new value "removed". The owner starts it on the field's page (**Remove from all files**, with a confirmation); it lists every file that had the field at the last scan.
- It goes through review → apply → undo (CLAUDE.md rule). `app/writer.py` stays the only writer: the ID3 handler treats `private:<owner>` as the group of PRIV frames with that owner. The snapshot keeps the removed frames (large data in the image store, like covers), so **undo restores them byte for byte**. After writing, the read-back check confirms the field is gone.
- Only ID3 (MP3, WAV, AIFF) has PRIV frames; other formats are refused. Tags, cover art and other programs' private data are not touched. Final tracks are skipped, as for every edit.
- Only removal, no editing: the data is binary and only its program understands it.
- The Tag fields page points out `PRIV:TRAKTOR4` (every Traktor-analysed file has it) and links to the removal.
- **On import** (setting *Remove Traktor data on import*, off by default, for owners who don't use Traktor): the import plan adds `private:TRAKTOR4` → removed for files that have it (read from the file's tags when the plan is made). It is written with the other import changes and undone with them; it doesn't block automatic imports.

## Consequences
- Undo data for big batches takes space in `/config/images` (each distinct frame once, by content hash).
- If the owner ever opens these files in Traktor, it analyses them again.

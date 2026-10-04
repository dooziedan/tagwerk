# 0009: How tags are written and undone
Date: 2026-10-04 · Status: Accepted

## Context
v0.6 is the first version that changes music files. A tag writer can damage a library quietly: dropping unknown fields, rewriting tags in a different version, or making changes impossible to reverse. The owner's files carry data from several tools (Picard, beaTunes, Rekordbox, record pools).

## Decision
- **Pending → review → apply → undo** (ADR 0003). Edits are saved as pending changes; files are only written by "Apply".
- **Only edited fields are touched.** The writer removes and re-adds just the frames/keys of the edited fields; everything else (unknown TXXX frames, cover art, hidden comments like iTunNORM) stays byte-for-byte as it was.
- **Exact undo.** Before writing, the current raw values of the affected fields are stored as a JSON snapshot (frame specs for ID3, value lists for Vorbis/MP4). Undo restores them exactly, e.g. `TBPM = 0` returns as `0`.
- **Values go where the file already keeps them** (a FLAC using `organization` for the label keeps it there); new fields follow Picard/Rekordbox conventions.
- **ID3 version**: existing tags keep their version; new ID3 tags are written as **v2.3**, the version DJ software reads most reliably. WAV/AIFF use ID3 (Navidrome reads it); a WAV's RIFF INFO chunk is left untouched.
- **Spec-conform values**: keys are written in standard notation (`Am`, `F#`) as ID3 `TKEY` defines, whatever notation was typed; BPM is an integer in ID3 (`TBPM`) and MP4 (`tmpo`), decimals are kept in Vorbis.
- **In-place writing** (like Picard), not copy-and-replace: keeps file ownership, permissions and hard links on Unraid.
- **Safety checks**: a file that changed on disk since the last scan is not written (rescan first); undo skips files changed after the change was applied, so newer edits are never overwritten; after writing, the file is re-read and compared with what was intended. Scanning and writing never run at the same time. The very first apply asks the owner to confirm a backup.

## Consequences
- Undo is reliable as long as the file wasn't changed in between; otherwise it refuses rather than guessing.
- The writer must be extended per field and format together with the reader (`app/tags.py`, `app/rawtags.py`); tests cover every field × every format, unrelated-field preservation and exact undo.
- Snapshots are stored per applied file in `changeentry` (small JSON); history grows with use and can be pruned later.

# 0039: Advanced tags: every tag field, changed through the same review → apply → undo
Date: 2026-10-13 · Status: Accepted

## Context
The track page lists every tag field of a file ("All tag fields": `TXXX:fBPM`, `PRIV:TRAKTOR4`, `encoder`, …), but the edit page only knows Tagwerk's own fields. To fix the rest (a wrong `TXXX:EnergyLevel`, an old `COMM:Songs-DB_Custom1`, a missing `MOOD`, a stray `encoder`), the owner had to open another tag editor, which bypasses Tagwerk's snapshots and undo ([issue #40](https://github.com/dooziedan/tagwerk/issues/40)).

## Decision
**A switch "Advanced tags" on a track's edit page** shows every field of the file, read from the file when the page opens (the database keeps shortened values only), grouped by tag system: ID3 (with its version), Vorbis, MP4, and RIFF INFO for WAV. Each field can be changed, removed (tick *Remove*) or given more values (*+ value*); *Add a field* adds new ones. Only on a single track's page; several tracks have different fields. Switched off, the section's inputs are ignored. It opens by itself while a track has pending advanced changes, and from the track page's "All tag fields → Edit them".

**Same flow as every edit.** Each field is one pending change, `raw:<system>:<name>` (`raw:id3:TXXX:MOOD`, `raw:vorbis:encoder`, `raw:mp4:----:com.apple.iTunes:MOOD`, `raw:riff-info:ISFT`), named exactly as the track page lists it. Its values are a JSON list of texts, because a field can hold several (Vorbis repeats a name, ID3v2.4 and MP4 keep lists) and a value can hold line breaks (lyrics): no separator would be safe. The Changes and History pages show them joined with "; ". `None` removes the field. Apply writes them with a snapshot first ([ADR 0009](0009-writing-tags.md)), reads the file back to check, and undo restores the snapshot.

**Text or not.** A field "holds text" when the writer can write it back exactly: ID3 text frames (incl. `TXXX`, `COMM`), lyrics (`USLT`) and links (`W…`, `WXXX`); every Vorbis comment except pictures; MP4 text atoms and freeform fields stored as UTF-8; RIFF INFO. Everything else (pictures, private data like `PRIV:TRAKTOR4`, ratings, MP4 numbers like `trkn` or `tmpo`, links whose name contains the link like `WCOM`, frames sharing one name) is shown and can only be removed. `app/rawtags.py` decides this once (`fields()`); the writer uses the same functions, and a test writes every text field of every fixture back unchanged.

**Editing keeps the field.** A changed ID3 frame is changed in place (its description, language and kind stay), with UTF-8 text (UTF-16 in v2.3). A Vorbis comment keeps the spelling the file uses; new Vorbis names are written in lower case, as Tagwerk lists them (Vorbis ignores case). New fields from a typed name follow Picard: `MOOD` becomes `TXXX:MOOD` (ID3), `mood` (Vorbis), `----:com.apple.iTunes:MOOD` (MP4); known frames (`TSRC`, `COMM:notes`, `©grp`) stay themselves. Names that can't hold text are refused, and so are ID3v2.4-only frames in an ID3v2.3 tag (mutagen would drop them when saving), and ID3 dates that aren't dates. In ID3v2.3 several values become one, joined with "/" (that's how v2.3 stores them); the check after writing knows this.

**RIFF INFO is written now, only by Advanced tags.** ADR 0009 left a WAV's RIFF INFO chunk untouched; normal edits still go to the WAV's ID3 tag. Advanced tags rewrite the `LIST`/`INFO` chunk with mutagen's chunk tools (sizes of the chunk and the file kept right, the audio moved, never re-encoded). The snapshot is the whole chunk as it was, so undo puts back the exact bytes. When every field is removed, the empty chunk stays in its place, so its undo is exact too. A WAV without ID3 gets no ID3 tag from a RIFF INFO change.

**The normal field wins.** A field that feeds a Tagwerk field (`TBPM` → BPM, `TXXX:CATALOGNUMBER` → Catalog number, `APIC` → Cover art; `used_as()` in `app/rawtags.py`) shows it as a badge. The two never both wait: staging a normal field (from the form, the audio, an online lookup, …) takes back pending advanced changes of the fields feeding it, and an advanced change of a field whose normal field has a pending change isn't saved (the page says so). In the same form, the normal field wins. The writer also writes advanced fields first, so a normal field written in the same go is the one that stays.

**All or nothing.** The edit form checks the normal fields and every advanced field before saving any of them.

Also: `GET /api/tracks/{id}/fields` lists a file's fields in full with their change names; `POST /api/changes` takes `raw`. Final tracks stay locked. Statistics → Tagwerk's work counts them as one row, *Advanced tags*.

## Consequences
- Every tag field can be fixed in Tagwerk, with review and exact undo, in all seven formats.
- Vorbis comment order may change on undo (values come back exactly, as with normal fields); everything else comes back byte for byte in the tests.
- Opening the edit page reads the file once (milliseconds). When the file can't be read (folder not mounted), the section says so and the rest of the page works.
- New tag systems or field kinds need reader (`rawtags.fields`) and writer support together; the round-trip test over all fixtures guards it.

# Roadmap

Each phase ends with something that can be run and tried. Phases are tracked as GitHub milestones.

## Phase 0: Setup ✅ (v0.1.0)
Project skeleton, Docker image with PUID/PGID, Unraid template, CI, documentation.
**Done when:** the container runs on Unraid and the start page shows both folders as OK.
Verified 2026-10-04 on Unraid 7.3.2.

## Phase 1: Library scan + dashboard ✅ (v0.2.0)
- Database with Alembic migrations.
- Read tags from MP3, FLAC, WAV, AIFF and M4A into one common format (RIFF INFO fallback for WAV).
- Scan the music folder (skip unchanged files) as a background job with progress.
- Dashboard: counts of artists, albums and tracks; format chart; size and duration; tracks missing tags.

**Done when:** the dashboard numbers match a test folder. WAV/AIFF tags are checked against Navidrome early.
Verified 2026-10-04: file count, size and playing time match `ffprobe` on the test folder. Still open: compare WAV/AIFF with Navidrome on the real library.

## v0.3: DJ and Collector modes ✅ (v0.3.0)
- OGG and Opus support (all formats Navidrome showed in the owner's library).
- New fields: BPM, key (any notation, shown as Camelot / Open Key / musical), comment, label, catalog number, ReplayGain, lyrics (embedded or `.lrc`).
- Mode switch with a dashboard per mode; MusicBrainz checks opt-in. Preferences stored in `/config`.
- Existing databases upgrade automatically, and older rows are re-read once to fill the new fields.

## v0.4: Tag fields page ✅ (v0.4.0)
- Every raw tag field of every file is stored at scan time (`rawtag` table).
- Overview with usage, empty/zero counts and sample values; detail page per field.
- Answered why few tracks show a BPM: many files store `0` ("unknown", written by MusicBrainz Picard).

## Goal (reviewed 2026-10-04)
Tagwerk manages the Unraid/Navidrome library, which becomes the owner's master library. New music arrives in a separate **import inbox**; Tagwerk tags it as far as it can on its own, asks the owner only where it's unsure, then moves finished tracks into the library. Rekordbox and the DJ SSD are out of scope (that would be a separate tool).

## v0.5: Browse and search (read-only) ✅ (v0.5.0)
- Track list with search and filters (missing BPM/key/year…, BPM = 0, format, folder); dashboard numbers link to these lists.
- Artists → albums → tracks.
- Track page: all tags, audio properties and raw fields.

**Done when:** every number on the dashboard can be clicked to see the tracks behind it.

## v0.5.1: Design foundation ✅ (v0.5.1)
- Design language with Calm and Pop themes, light and dark; logo and Unraid icon; cross-browser screenshot checks incl. Safari's engine. See [design.md](design.md).

## v0.6: Editing with review, apply and undo (the writing engine) ✅ (v0.6.0)
- Edit one track or many at once (e.g. a label for a whole album) → pending changes → review *old → new* → apply → undo.
- Tag writing for all 7 formats, mapped back to the same fields the reader uses (ID3 for WAV/AIFF, Vorbis, MP4).
- The edit form follows the mode: BPM, key, comment, label first in DJ mode; album fields first in Collector mode.
- Owner makes a backup before the first real apply.

**Done when:** an edit made in the UI shows up in Navidrome and another tag tool, and can be undone.

## v0.7: Import inbox and first-run setup
**Status:** steps 1–4 ✅ in v0.7.0 (inbox, suggestions, review and import with cover, Navidrome rescan); v0.7.1 rescans only the chosen Navidrome library. Step 5 ✅ the setup wizard (folder layouts, automatic import, genre map and filename pattern in Settings). New genre folders are proposed on the Changes page instead of created on their own ([ADR 0010](decisions/0010-new-genre-folders.md)). Duplicates are marked in the inbox and inbox files can be moved to a trash ([ADR 0011](decisions/0011-inbox-duplicates-and-trash.md)).

- Optional **Import** path in the Unraid template, separate from the library (Navidrome never sees untagged tracks).
- **First-run setup wizard:** mode, key notation, inbox, library folder pattern and **how independently Tagwerk may work** (always ask / auto-apply confident results). All changeable later in Settings.
- Inbox pipeline, local steps: read tags, parse **filenames** (record pools, stores, promos, downloads), clean-up rules (BPM 0 → empty, spacing, "feat.", genre spelling, misplaced Discogs IDs).
- Inbox page: "done" and "needs your help", with Tagwerk's best guesses to confirm or correct.
- Finished tracks are **moved into the library** by the owner's folder pattern (copy → verify → delete), then Navidrome rescans. By default **the filename never changes**: only the folder (and the tags) do.
- Folder patterns offered in the wizard (the owner browses the share in a file explorer, so folders and filenames must be easy to remember):
  - **Genre buckets** (proposed default): `Genre/<original filename>`, with 10–15 broad buckets the owner picks; genre tags are mapped onto them ("Deep House" → `House`), unknown → `_Unsorted`.
  - **Subgenres**: the genre tag holds the main genre first, subgenres after it (`Drum & Bass; Liquid`); the first value picks the folder. A small, editable **genre map** (plain text in the settings table, shipped with common electronic genres and spelling variants like `DnB` → `Drum & Bass`) sorts tracks tagged only with a subgenre and proposes adding the main genre. One dictionary lookup per imported track: no extra database or service.
  - **Artist**: `Artist/<original filename>`.
  - **Date added**: `2026/2026-10/<original filename>`.
  - **Custom pattern** with placeholders for the folder (e.g. `{genre}/{year}`); the filename is never part of it.
  - **Import never renames files**: the file keeps its exact name. Renaming is a separate, optional feature for **final** tracks (see below). The original filename is never written into tags.
  - Real albums stay together in an album folder.
  - Only new tracks from the inbox are sorted; reorganising the existing library is a separate, later feature (check Navidrome's handling of moved files first).

## After v0.7: Final tracks
**Status:** ✅ built (Final check page, lock, renaming after Navidrome scanned, remove mark with name choice; [ADR 0012](decisions/0012-final-tracks.md)). Checked first: Navidrome keeps play counts and ratings of renamed files unless tags changed in the same scan.

- A **Final check** page for library tracks: fully tagged tracks (title, artist, genre, BPM, key, cover) shown one at a time with all tags and the cover; **Mark as final** and go to the next.
- The mark itself is stored **only in Tagwerk's database**: no tag is written for it.
- Final tracks are **locked**: they can't be edited in Tagwerk until unlocked (batch edits skip them and say so). If another program changes the file, the mark stays but the track is flagged "changed outside Tagwerk".
- **Renaming happens only when "Mark as final" is pressed**, and only if the owner enabled it (wizard, changeable in Settings). Before that, tags can be written any number of times without touching the filename. The page shows the new name before confirming. **Removing the final mark asks what to do with the name**: keep the current name, go back to the name before it was marked final, or type a name.
- **Settings → Filename for final tracks**: which tags make up the name, e.g. `{artist} - {title} [{bpm} {key}]` (empty bracket parts disappear; characters Windows/SMB don't allow are replaced), with a live preview.
- Before building the renaming: check how Navidrome keeps play counts and ratings for renamed files.

## Before 1.0: Convert to AIFF ✅
Lossless tracks (FLAC, WAV, ALAC) to AIFF with ffmpeg, all tags and pictures, bit-exact; the AIFF lands by the import folder layout, the original in `/originals` ([ADR 0013](decisions/0013-convert-to-aiff.md)).

## v0.8: Online identification
**Status:** ✅ for the inbox ([ADR 0014](decisions/0014-online-identification.md)): MusicBrainz, AcoustID, Discogs, Deezer, iTunes; agreement-based confidence; cover suggestions. Library tracks (0.8.1): Look up online; sure values become pending changes.

- Metadata source interface; sources: AcoustID fingerprint (fpcalc in the image), MusicBrainz, Discogs (free token), and public store APIs if their terms allow (iTunes Search, Deezer).
- Cover art (Cover Art Archive, Discogs, store artwork).
- Every proposed value has a confidence; the owner's autonomy setting decides what is applied automatically.

## v0.8.2: Play bar
**Status:** ✅ Listen to library and inbox tracks in a play bar that keeps playing across pages ([ADR 0015](decisions/0015-player.md)).

## v0.9: BPM and key from the audio
**Status:** ✅ Essentia in the image; BPM (exact to 0.05) and key tuned for bass-heavy music, half/double time settled by genre, filename and online sources; inbox suggestions, pending changes for empty fields, flags for differing tags ([ADR 0017](decisions/0017-audio-analysis.md)). Also: **Fix IDs** for MusicBrainz fields holding Discogs numbers, which move to their own fields ([ADR 0018](decisions/0018-musicbrainz-and-discogs-ids.md)).

- Detect tempo and key inside the container. First step: verify an analysis library that runs in the image and on the current Python version.
- Flag likely half-/double-time values (e.g. 87 instead of 174).

## v1.0: Visual rebrand
A new look before 1.0: space-like visuals and colours inspired by Orbit Stage, calmer card and page design inspired by SoulSync, a touch of glassmorphism (with solid fallbacks and reduced motion). Direction proposed and agreed before coding; an ADR.

## Navidrome integration (alongside v0.6–v0.8)
- Connection settings and test button; rescan after apply and after moving inbox tracks.
- Navidrome stats and most played on the dashboard.

## Later / ideas
- **Apply changes one by one**: tick the pending changes to apply instead of always applying all.
- **Most played tracks**: play counts come from the DJ hardware and software, so this depends on reading Rekordbox data (out of scope so far).
- **Online keys**: an extra source with tempo and key (e.g. GetSongBPM, if its terms allow) to confirm the audio analysis; Deezer only has BPM.
- **Remove all private data** in one action, and a finder for PRIV data Tagwerk can't see (a second ID3 tag, a tag at the end of an MP3, ID3 in front of a FLAC).
- Energy or danceability from the audio (Essentia) for statistics and set prep.
- **Daily library snapshot** for trend lines in Tagwerk's work (set-ready, missing BPM/key/genre/cover over time), one row per day ([ADR 0020](decisions/0020-tagwerks-work.md)).
- Harmonic mixing helpers (compatible keys), BPM/key filters for set prep.
- Batch jobs for the existing library (e.g. look up everything without IDs).
- Last.fm genres.
- Login protection.

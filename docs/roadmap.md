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

## v0.6: Editing with review, apply and undo (the writing engine)
- Edit one track or many at once (e.g. a label for a whole album) → pending changes → review *old → new* → apply → undo.
- Tag writing for all 7 formats, mapped back to the same fields the reader uses (ID3 for WAV/AIFF, Vorbis, MP4).
- The edit form follows the mode: BPM, key, comment, label first in DJ mode; album fields first in Collector mode.
- Owner makes a backup before the first real apply.

**Done when:** an edit made in the UI shows up in Navidrome and another tag tool, and can be undone.

## v0.7: Import inbox and first-run setup
- Optional **Import** path in the Unraid template, separate from the library (Navidrome never sees untagged tracks).
- **First-run setup wizard:** mode, key notation, inbox, library folder pattern and **how independently Tagwerk may work** (always ask / auto-apply confident results). All changeable later in Settings.
- Inbox pipeline, local steps: read tags, parse **filenames** (record pools, stores, promos, downloads), clean-up rules (BPM 0 → empty, spacing, "feat.", genre spelling, misplaced Discogs IDs).
- Inbox page: "done" and "needs your help", with Tagwerk's best guesses to confirm or correct.
- Finished tracks are **moved into the library** by the owner's pattern (copy → verify → delete), then Navidrome rescans.

## v0.8: Online identification
- Metadata source interface; sources: AcoustID fingerprint (fpcalc in the image), MusicBrainz, Discogs (free token), and public store APIs if their terms allow (iTunes Search, Deezer).
- Cover art (Cover Art Archive, Discogs, store artwork).
- Every proposed value has a confidence; the owner's autonomy setting decides what is applied automatically.

## v0.9: BPM and key from the audio
- Detect tempo and key inside the container. First step: verify an analysis library that runs in the image and on the current Python version.
- Flag likely half-/double-time values (e.g. 87 instead of 174).

## Navidrome integration (alongside v0.6–v0.8)
- Connection settings and test button; rescan after apply and after moving inbox tracks.
- Navidrome stats and most played on the dashboard.

## Later / ideas
- Harmonic mixing helpers (compatible keys), BPM/key filters for set prep.
- Batch jobs for the existing library (e.g. look up everything without IDs).
- Last.fm genres.
- Login protection.

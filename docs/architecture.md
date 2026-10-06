# Architecture

## Overview

```
 Browser ──HTTP──► FastAPI app (one container)
                      │
                      ├─ pages (Jinja2 + htmx)  ─┐ same routes, documented at /docs
                      ├─ REST API               ─┘
                      ├─ SQLite DB  ──────────► /config/tagwerk.db
                      ├─ tag reader/writer ───► /music  (mutagen)
                      ├─ metadata sources ────► MusicBrainz, Cover Art Archive, … (internet)
                      └─ Navidrome client ────► Navidrome (Subsonic API, via host IP)
```

## The change flow (core design)

Files are never modified directly from a form or a lookup:

1. **Scan:** read tags from files into the database (the "current file state").
2. **Edit / Lookup:** manual edits and source results become *pending changes* in the database.
3. **Review:** a diff shows old → new per field and file.
4. **Apply:** tags are written. The old tags are saved first as a snapshot, which makes undo possible.
5. **Sync:** Navidrome is asked to rescan.

## Code layout

| Path | Purpose | Since |
|---|---|---|
| `app/main.py` | Creates the FastAPI app, registers routes | 0.1 |
| `app/config.py` | Settings from environment variables | 0.1 |
| `app/templates/`, `app/static/` | HTML pages; vendored Pico CSS and htmx | 0.1 |
| `app/db.py`, `app/models.py`, `app/migrations/` | Database tables and Alembic migrations (run on every start) | 0.2 |
| `app/tags.py` | Reads ID3 / Vorbis / MP4 / RIFF INFO into one set of fields ([ADR 0005](decisions/0005-reading-tags.md)) | 0.2 |
| `app/scanner.py` | Walks the music folder, updates the `track` table, skips unchanged files | 0.2 |
| `app/library.py` | Track filters, sorting, paging; artists and albums. The dashboard counts with the same conditions, so every number matches its list | 0.5 |
| `app/stats.py` | Dashboard numbers (using `app/library.py` conditions), each with the URL of its track list | 0.2 |
| `app/covers.py` | Cover art for display: embedded or `cover.jpg`/`folder.jpg` next to the file | 0.5 |
| `app/routes/` | Pages and API, one module per feature (`system`, `dashboard`, `scan`, `settings`, `fields`, `library`, `changes`, `inbox`) | 0.2 |
| `app/templating.py` | Jinja2 setup and display filters (sizes, durations) | 0.2 |
| `app/charts.py` | SVG geometry for charts (Camelot wheel) | 0.3 |
| `app/rawtags.py` | Collects every raw tag field of a file; knows which raw names feed which Tagwerk field | 0.4 |
| `app/fields.py` | Statistics for the Tag fields page | 0.4 |
| `app/writer.py` | **The only code that writes music files**: writes edited fields per format, captures snapshots, undoes ([ADR 0009](decisions/0009-writing-tags.md)) | 0.6 |
| `app/changes.py` | Pending changes, apply and undo (run as jobs) | 0.6 |
| `app/keys.py` | Parse keys in any notation to Camelot; display as Camelot / Open Key / musical | 0.3 |
| `app/preferences.py` | Mode, key notation, MusicBrainz visibility, stored in the `appsetting` table | 0.3 |
| `app/navidrome.py` | Asks Navidrome to rescan after a write (Subsonic `startScan`, salted-token login, standard library only) | 0.7 |
| `app/inbox.py` | Keeps the `inboxtrack` table in sync with the import folder; the owner's values per track (`inboxvalue`) and the review of each field | 0.7 |
| `app/proposals.py` | Suggestions from filenames and clean-up rules (pure functions, recalculated when shown) | 0.7 |
| `app/genres.py` | The genre map: spelling variants and subgenre → main genre | 0.7 |
| `app/importer.py` | Import: write tags, copy → verify → delete into the library (filename unchanged); undo moves back | 0.7 |
| `app/convert.py` | Converting lossless tracks to AIFF with ffmpeg (ffprobe decides what is lossless): check, convert, verify, move the original to `/originals`; undo ([ADR 0013](decisions/0013-convert-to-aiff.md)) | 0.7 |
| `app/tagcopy.py` | Translates all tags and pictures of a FLAC, WAV or ALAC file into ID3 frames (Picard's mapping) for the AIFF | 0.7 |
| `app/final.py` | Final tracks: what's ready, mark/unmark (lock), renaming by the filename pattern after Navidrome has scanned ([ADR 0012](decisions/0012-final-tracks.md)) | 0.7 |
| `app/duplicates.py` | Finds likely library copies of inbox tracks (identical file, MusicBrainz ID, artist + title) ([ADR 0011](decisions/0011-inbox-duplicates-and-trash.md)) | 0.7 |
| `app/trash.py` | The inbox trash: deleting moves inbox files to `.tagwerk-trash/`, restore, removal after 30 days | 0.7 |
| `app/folders.py` | Proposes new genre folders for tracks in `_Unsorted`; creates them and moves the files only after the owner's OK; undo moves back ([ADR 0010](decisions/0010-new-genre-folders.md)) | 0.7 |
| `app/images.py` | Content-addressed image store in `/config/images` (uploaded covers, covers kept for undo) | 0.6.1 |
| `app/naming.py` | Folder and filename patterns (`{artist} - {title} [{bpm} {key}]`): empty bracket parts vanish, share-safe characters | 0.7 |
| `app/routes/setup.py` | The setup wizard; its `apply_choices` is shared with Settings, so a choice means the same in both | 0.7 |
| `app/navigation.py` | Where "← Back" and "after saving" lead (only pages of the app) | 0.7 |
| `app/sources/` | Online metadata sources behind one interface (`base.py`): MusicBrainz, AcoustID (fpcalc), Discogs, iTunes, Deezer | 0.8 |
| `app/identify.py` | Asks the sources about inbox tracks, scores the matches, stores them (`onlinelookup`) and turns agreement into suggestions and a cover ([ADR 0014](decisions/0014-online-identification.md)) | 0.8 |
| `app/routes/lookup.py` | Look up online for library tracks: sure values become pending changes, "Use these values" stages one result | 0.8.1 |
| `app/routes/player.py`, `app/static/player.js` | The play bar: serves audio (range requests; ffmpeg → MP3 for AIFF/ALAC). Pages swap in place with hx-boost so playback continues ([ADR 0015](decisions/0015-player.md)) | 0.8.2 |
| `app/audio_analysis.py` | BPM and key from the audio with Essentia (read-only; also runnable by hand: `python -m app.audio_analysis FILE`) ([ADR 0017](decisions/0017-audio-analysis.md)) | 0.9 |
| `app/analysis.py` | Runs the analysis per track in a low-priority process, stores results (`inboxanalysis`, `libraryanalysis`), combines them with genre, filename and online BPMs, stages sure values | 0.9 |
| `app/ids.py` | MusicBrainz ID fields holding other values: what's wrong, and the fix (Discogs numbers to their own fields) ([ADR 0018](decisions/0018-musicbrainz-and-discogs-ids.md)) | 0.9 |
| `app/jobs.py` | Background jobs (scan, inbox check, apply, import, undo) in a thread; one shared lock so they never overlap | 0.2 |
| `docker/entrypoint.sh` | Applies PUID/PGID/UMASK, then starts the app | 0.1 |
| `unraid/tagwerk.xml` | Unraid container template | 0.1 |

## Runtime

- One process: `uvicorn` serving FastAPI. No external services.
- Database: SQLite at `/config/tagwerk.db` in WAL mode, so the dashboard can read during a scan.
- Data model so far: one `track` row per audio file (artists and albums are derived from it), plus `rawtag` (every tag field of every file, as stored), `pendingchange`, `changeset`/`changeentry` (applied changes with undo snapshots) and `appsetting` for preferences.
- `track.scan_version` records which tag-reader version read a row. Raising `SCAN_VERSION` in `app/scanner.py` makes the next scan re-read older rows once.
- Everything needed at runtime ships in the Docker image. Only `/config` and `/music` come from the host.
- Persistent state lives only in `/config`. The container can be deleted and recreated at any time.
- Runs as `PUID:PGID` (Unraid: `99:100`). Only `/config` is chowned on start, never `/music`.

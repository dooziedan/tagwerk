# Roadmap

Each phase ends with something that can be run and tried. Phases are tracked as GitHub milestones.

## Phase 0: Setup 🚧 (v0.1.0)
Project skeleton, Docker image with PUID/PGID, Unraid template, CI, documentation.
**Done when:** the container runs on Unraid and the start page shows both folders as OK.

## Phase 1: Library scan + dashboard ✅ (v0.2.0)
- Database with Alembic migrations.
- Read tags from MP3, FLAC, WAV, AIFF and M4A into one common format (RIFF INFO fallback for WAV).
- Scan the music folder (skip unchanged files) as a background job with progress.
- Dashboard: counts of artists, albums and tracks; format chart; size and duration; tracks missing tags.

**Done when:** the dashboard numbers match a test folder. WAV/AIFF tags are checked against Navidrome early.
Verified 2026-10-04: file count, size and playing time match `ffprobe` on the test folder. Still open: compare WAV/AIFF with Navidrome on the real library.

## Phase 2: Browse + manual editing
- Artists → albums → tracks, with search and filters (e.g. "missing year").
- Edit a track or a whole album → pending changes → review diff → apply (snapshot first) → undo.

**Done when:** an edit made in the UI is visible in another tag tool and can be undone.

## Phase 3: Navidrome
- Connection settings plus a "test connection" button.
- Navidrome stats and most-played on the dashboard.
- Rescan triggered after apply.

**Done when:** a tag change appears in Navidrome without manual steps.

## Phase 4: MusicBrainz
- Metadata source interface. MusicBrainz is the first implementation.
- Album search → choose a release → match tracks → pending changes (still editable).
- Cover art from the Cover Art Archive (embedded and/or `cover.jpg`).

**Done when:** a messy test album is tagged completely from MusicBrainz.

## Phase 5: Later / ideas
- Batch jobs ("look up all albums without MusicBrainz IDs").
- AcoustID fingerprinting for untagged files.
- More sources: Discogs, Last.fm genres.
- Rename and organize files by pattern.
- Login protection.

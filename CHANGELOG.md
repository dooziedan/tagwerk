# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.1] - 2026-10-04

### Changed
- DJ mode shows keys on a **Camelot wheel** (major outside, minor inside, 12 at the top), shaded by track count with the count on every segment. The grid is still available under "Show as table".
- Lossy files are now flagged below **320 kbps** (was 256), with 2% tolerance for encoders that report 319 kbps.

### Fixed
- Keys stored as `initial_key` (with underscore) in FLAC/OGG/Opus are now read.

## [0.3.0] - 2026-10-04

### Added
- **DJ and Collector modes**, switchable in the menu and saved in `/config`.
  - DJ: tempo spread, key grid, BPM & key coverage, lossless share, lossy files below 256 kbps, missing BPM/key/label/comment.
  - Collector: decades, genres, lyrics and ReplayGain coverage, missing album tags.
- OGG and Opus files.
- New fields read from all formats: BPM, key, comment, label, catalog number, ReplayGain track gain, embedded lyrics, and `.lrc` lyrics files next to tracks.
- Keys in any common notation (Am, A minor, 8A, 1m, F#/Gb…) are recognized and shown as Camelot, Open Key or musical notation (setting). Unrecognized key tags are counted.
- Settings page and API: `GET`/`PUT /api/settings`.

### Changed
- MusicBrainz checks are now optional and off by default.
- WAV files with only RIFF INFO tags now also show their comment.
- On phones, the menu shows only the mode switch and Settings.

### Upgrade notes
- The database upgrades automatically. The first scan after updating re-reads every file once to fill in the new fields, so it takes as long as a first scan.

## [0.2.0] - 2026-10-04

### Added
- Library scan: reads MP3, FLAC, WAV, AIFF and M4A tags into one common format, including RIFF INFO tags in WAV files without ID3. Runs in the background with a progress bar; unchanged files are skipped on rescans, deleted files are removed. Read-only.
- Dashboard: tracks, artists, albums, total size and playing time, formats, missing tags, files without any tags, and MusicBrainz fields holding non-MusicBrainz IDs (e.g. Discogs).
- SQLite database in `/config/tagwerk.db`, upgraded automatically on start (Alembic migrations).
- API: `POST /api/scan`, `GET /api/scan`, `GET /api/stats`.

### Changed
- The start page is now the dashboard. Setup problems (missing music folder, app data not writable, database error) are shown at the top instead of a checklist.

## [0.1.0] - 2026-10-04

### Added
- Project setup: FastAPI app, start page with a setup check for the music and app data folders.
- `/health` endpoint and Docker healthcheck; `/api/status` endpoint.
- Docker image with PUID/PGID/UMASK support (Unraid defaults 99/100/022).
- Unraid container template (`unraid/tagwerk.xml`).
- CI (lint + tests), image publishing to GHCR, Dependabot.
- Documentation: README, architecture, development guide, roadmap, decision records.
- Licensed under AGPL-3.0-or-later; source code link in the page footer.

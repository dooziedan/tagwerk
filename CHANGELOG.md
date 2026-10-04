# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.6.0] - 2026-10-04

### Added
- **Editing tags** for all 7 formats: title, artist, album, album artist, track, disc, date, genre, BPM, key, comment, label, catalog number.
  - One track: **Edit tags** on the track page. The form follows the mode (DJ: BPM, key, genre, comment, label first).
  - Many tracks: tick tracks in the track list → **Edit selected**, or **Edit all matching** for everything the current filter shows. Only ticked fields change.
- **Changes** page (menu, with a count): every pending change as old → new, discard single changes or all, then **Apply**. Nothing is written before that.
- **History** with **Undo** per apply. Undo restores the exact previous values.
- Safety: the first apply asks you to confirm a backup; files changed since the last scan aren't written; undo never overwrites newer edits; scanning and writing never run at the same time; every written file is re-read and checked.
- API: `GET/POST/DELETE /api/changes`, `POST /api/changes/apply`, `GET /api/changes/job`, `GET /api/changesets`, `POST /api/changesets/{id}/undo`.

### Notes
- Keys are written in standard notation (Am, F#) whatever you type; BPM is stored as a whole number in MP3/WAV/AIFF/M4A (format rule), with decimals in FLAC/OGG/Opus.
- New ID3 tags are written as v2.3 for DJ software; existing tags keep their version. See [ADR 0009](docs/decisions/0009-writing-tags.md).

## [0.5.1] - 2026-10-04

### Added
- **Design language** ([docs/design.md](docs/design.md)) with two themes in Settings: **Calm** (one accent colour, default) and **Pop** (the full palette: Charcoal Blue, Verdigris, Jasmine, Sandy Brown, Burnt Peach). Both in light and dark; **Appearance** can follow the system or be fixed to light or dark.
- **Inter** as the app font, shipped with the app (no internet needed), so Tagwerk looks the same on Mac, Windows, Linux, iPhone and Android.
- **Logo**: a luggage tag with level bars, in the menu, as browser icon, Apple touch icon and **Unraid icon** (the Docker list no longer shows a blank icon after re-adding the template).
- `scripts/screenshots.py`: screenshots of the main pages in Chromium, Firefox and WebKit (Safari), both themes, light and dark, desktop and phone, run in Playwright's Docker image.

### Changed
- Camelot wheel uses the standard Camelot colours (now in the familiar clockwise order) in every theme, with readable labels on all 24 segments.
- Colours come from design tokens (`app/static/theme.css`) with measured contrast, instead of Pico's default blue.

- Dashboard order: **missing tags first**; in DJ mode then keys, formats and tempo, with **genres at the bottom**.
- "Most common keys" under the wheel is collapsed by default.
- Headline tiles are centred, units shown smaller ("834.1 KB"), and values shrink slightly on narrow windows.

### Fixed
- Key labels on the Camelot wheel were underlined since segments became links.
- Long values like "834.1 KB" ran to the edge of their tile at window widths around 1000–1200 px.

## [0.5.0] - 2026-10-04

### Added
- **Track list** (menu → Library → Tracks): search title, artist, album, label and path; filter by missing tag, format, key, tempo range, genre, decade, folder, artist, album, raw tag field and more; sort by any column; 50 tracks per page. Columns follow the mode (DJ: BPM, key, genre, label; Collector: album, track, year, genre). Active filters show as chips you can remove one by one.
- **Every number on the dashboard is a link** to exactly those tracks: missing tags, formats, genres, decades, tempo ranges, Camelot wheel segments, lossless / low-bitrate / untagged notes.
- **Track page**: all tags, audio properties, file details, every raw tag field, and the cover (embedded, or `cover.jpg` / `folder.jpg` next to the file).
- **Artists** and **Albums** pages with search.
- Tag fields: "Show all tracks with this field", and every value's count links to its tracks.
- DJ dashboard: how many files store BPM as 0, linked to the list.
- API: `GET /api/tracks`, `/api/tracks/{id}`, `/api/artists`, `/api/albums`.

### Changed
- Menu: "Library" dropdown (Tracks, Albums, Artists, Tag fields). On phones, Settings moved into it.
- Genres are matched the same way everywhere: "House;Techno" and "House; Techno" both count as House and Techno.

## [0.4.0] - 2026-10-04

### Added
- **Tag fields page** (menu → Tag fields, or the link under "Missing tags"): every tag field found in your files, with its tag system, which Tagwerk field it feeds (or "ignored"), how many files have it, how many values are empty or `0`, and the most common values. Search, filter by tag system, and show only used or ignored fields.
- Detail page per field: all values with counts and example files.
- API: `GET /api/fields`, `GET /api/fields/detail?system=…&name=…`.

### Fixed
- Files that couldn't be read are now retried on every scan, instead of staying "unreadable" until the file changes.

### Upgrade notes
- The first scan after updating re-reads every file once to record all tag fields.

## [0.3.2] - 2026-10-04

### Fixed
- The Camelot wheel could show white segments with white text in some browsers, because its colours depended on a newer CSS feature (`color-mix`). Colours are now written into the chart itself and work in every browser.

### Changed
- Redesigned Camelot wheel: each key number has its own colour, major keys stronger than minor, empty keys grey; the track count is the main bold number in each segment, with smaller key names.
- "Most common keys" list with counts and percentages below the wheel, replacing the "Show as table" grid.

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

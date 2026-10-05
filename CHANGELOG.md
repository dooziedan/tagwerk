# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.8.3] - 2026-10-05

### Fixed
- **Tag fields** page no longer gets huge and slow from Traktor data: private ID3 fields (e.g. `PRIV:TRAKTOR4`, where Traktor stores its waveform, beat grid and cue points) are listed once by their program instead of once per file with all their data in the name. The next scan re-reads every file once to apply this.

## [0.8.2] - 2026-10-05

### Added
- **Play bar**: a ▶ button on tracks (list, track page, inbox) starts the track in a bar at the bottom of the window with play/pause, a progress bar you can click to jump, and stop (which also hides the bar). The **space bar** pauses and resumes. Its symbols are drawn shapes, so they look the same on every device. One track at a time, no queue. Formats browsers can't play (AIFF, ALAC) are converted to MP3 on the fly with ffmpeg; files are never changed.
- The play bar has a **volume button**: hover it and a slider pops up above it; click it to mute and unmute. Volume changes glide smoothly, and the level is remembered in your browser. On phones and tablets the button is hidden: the volume buttons of the device set the volume.
- **Music keeps playing when you change pages**: links and forms now replace only the page part of the window instead of reloading everything.

### Changed
- **Look up online** shows the results by itself as soon as the sources have answered, on track pages and in the inbox; no need to reload the page.
- Questions before big or destructive actions (move to trash, undo, look up all tracks) now appear in Tagwerk's own box instead of the browser's pop-up, which some browsers block. **Move to trash** in the inbox did nothing in such browsers.

### Fixed
- Browsers load changed styles and scripts right away instead of an old cached copy (each file's URL carries a fingerprint of its content).

## [0.8.1] - 2026-10-04

### Added
- **Look up online for library tracks**: on a track's page, for ticked tracks in the track list, or for all tracks matching the list's filters. Values for empty fields that two sources agree on (and a cover) become **pending changes** for you to review and apply; everything else is shown on the track page with **Use these values**. Fields you already edited and final tracks are left alone.
- Every online result says why it matches as it does, e.g. *"20 % match · same title and artist, but 3:49 long (this file: 0:01)"* or *"another version of the title, same artist"*.

## [0.8.0] - 2026-10-04

### Added
- **Online identification** of inbox tracks: Tagwerk asks MusicBrainz, AcoustID (recognises a track by its sound), Discogs, Deezer and iTunes, and suggests what they find for empty fields: album, release date, genre, label, catalog number, BPM, and cover art. A value is **sure** when two sources agree (or the audio matches clearly), otherwise marked *check*; tags in the file always win. The track's review page shows every source's result with its match, a link, **Use these values** and **Look up again**.
- **Settings → Online lookups**: switch each source on or off. AcoustID and Discogs need free keys (**AcoustID Key**, **Discogs Token** in the container settings); the others work without an account. Only artist, title and a fingerprint of the sound are sent.

### Changed
- CI installs ffmpeg, so the conversion tests run there too (they were skipped).

## [0.7.4] - 2026-10-04

### Added
- **Final check** (Library menu): complete tracks (title, artist, genre, BPM, key, cover) one at a time, with **Mark as final** or **Skip**. Final tracks are locked against edits (batch edits skip them and say so) and show **✓ Final** on their page. The mark is kept in Tagwerk only; nothing is written into the file.
- **Renaming final tracks** (if switched on in Settings → Final tracks): marking renames the file by your pattern, e.g. `Artist - Title [126 8A].mp3`, in the same folder; a `.lrc` file goes along; nothing is overwritten. Before renaming, Tagwerk makes sure Navidrome has scanned the file's current tags, so play counts and ratings stay with the track.
- **Remove final mark** on a track's page: keep the name, go back to the name before it was marked final, or type a new one. Marking can also be undone from the History page.
- Track list filters **Final** and **Final, changed outside Tagwerk** (when another program wrote to a final track).
- **Convert to AIFF** for lossless tracks (FLAC, WAV, ALAC): tick tracks in the track list (or open a track) and choose **Convert to AIFF…**. A review page shows where each AIFF goes (your import folder layout, same filename) and which tracks are skipped (lossy files, including compressed audio inside a WAV; AIFFs). Every tag and picture is carried over, the new file is checked against the original (length, tags, cover) before anything moves, and the original goes to the new **Original Files** folder (`/originals`, set it in the Unraid template) for you to decide about. Undo from the History page.
- The Docker image now includes ffmpeg (for converting), so it is about twice as big.

## [0.7.3] - 2026-10-04

### Added
- **Duplicates in the inbox**: tracks that look like one you already have (identical file, same MusicBrainz recording, or same artist and title with about the same length; the mix name counts) are marked **In library** and get their own tab. The track's page compares both copies (where, format, bitrate, length, size).
- **Move to trash** for inbox files, on the track's page or for ticked tracks in the list. Deleted files wait in `.tagwerk-trash` inside the import folder; **Recently deleted** on the Inbox page restores them, and they are removed for good after 30 days. Library files are never deleted.
- Automatic import leaves likely duplicates in the inbox for you to decide.
- Importing a track whose filename is already in its library folder is greyed out with the reason, instead of failing after the click.

### Changed
- The DJ / Collector switch left the header; choose the mode in **Settings** (or the setup wizard). On phones the name "Tagwerk" shows next to the logo again.
- The **Library** menu in the header looks like the other header links (it was drawn as a form field).

### Fixed
- On phones, **Scan library** is as wide as the tiles below it.

## [0.7.2] - 2026-10-04

### Added
- **Setup wizard** on first start (also after updating, with your current settings filled in): checks the folders and Navidrome, then asks how you work (DJ/Collector, key notation), where imported tracks go, how independently Tagwerk may work, and whether final tracks get renamed. **Skip setup** keeps the defaults. Everything can be changed later in Settings, and **Settings → Run setup again** goes through it once more.
- **Import folders** of your choice: genre folders (optionally only your main genres; others go to `_Unsorted`), artist folders, date added (`2026/2026-10/`), or your own pattern like `{genre}/{added_year}`. Live examples from your own tracks. Filenames still never change on import.
- **Automatic import** (optional): complete tracks (title, artist, genre, BPM, key, cover; every suggestion sure; file unchanged for 2 minutes) are imported without asking. The inbox is also checked every 5 minutes in the background. Each automatic import shows on the Inbox page with *Details and undo*.
- **New genre folders after your OK**: Tagwerk no longer creates a genre folder on its own. A track whose genre has no folder yet (e.g. *Rock*) is imported into `_Unsorted`, and the **Changes** page proposes the folder: which folder is created and which files move into it (filenames unchanged, `.lrc` lyrics move along). **Create folder and move** does it and adds the genre to your main genres; **Keep in _Unsorted** stops asking for that genre. Moves show up in the History and can be undone.
- **Settings → Genre map**: edit spelling variants (`=`) and subgenres (`>`), or go back to the built-in map.
- **Settings → Final tracks & filenames**: the filename pattern for final tracks (e.g. `{artist} - {title} [{bpm} {key}]`), with clickable placeholders and a live preview. Used once marking tracks as final arrives.

### Changed
- `PUT /api/settings` now changes only the settings that are sent; all others stay as they are.
- Genre folders with no main genres ticked: only the genre folders already in your library are used; new ones are proposed instead of created.
- Artist folders use the track artist, not the album artist (no "Various Artists" folder for compilation tracks).

## [0.7.1] - 2026-10-04

### Added
- **Navidrome with several libraries**: the new optional field **Navidrome Library** (`NAVIDROME_LIBRARY`, e.g. `Music Library`) names the library that uses your music folder. Only that one is rescanned (Navidrome 0.59+; older versions scan all). **Test connection** lists Navidrome's libraries and says which one is rescanned; a misspelled name is reported with the real names.

## [0.7.0] - 2026-10-04

### Added
- **Import inbox** (v0.7, step 1): an optional **Import Inbox** folder in the Unraid template (`/import`). The new **Inbox** page lists the tracks in it with their tags and what each one is missing (title, artist, genre, BPM, key, cover). Read-only for now: nothing is changed or moved yet. Inbox tracks are kept apart from the library, so they don't appear in counts or lists.
- **Inbox suggestions** (v0.7, step 2): for each inbox track Tagwerk shows what it would change, still read-only:
  - from the **filename**: artist, title, BPM and key (`01. Artist - Title (Extended Mix) [128 8A].mp3`; track numbers, label brackets and underscores are handled). Unclear names are marked **check**.
  - **clean-up** of existing tags: spacing, "ft." → "feat.", genre spelling (`DnB` → `Drum & Bass`), and the main genre before subgenres (`Liquid` → `Drum & Bass; Liquid`).
  - Mix names in square brackets are kept (`[Carvalho Drunk Mix]` → `(Carvalho Drunk Mix)`), a BPM after the mix name is read (`(Edit) 124`), and names in CAPITALS or lower case get normal capitalisation (marked **check**).
  - **Track types in brackets get capital letters**, as DJs and stores write them (MusicBrainz writes them in lower case): `(club remix)` → `(Club Remix)`, `[vip]` → `[VIP]`. Remixer names stay as written.
  - Title tags that repeat the artist or the BPM are tidied: `Haddaway - What is Love` → `What is Love`, `Body (Zillionaire Edit) 126` → `Body (Zillionaire Edit)`.
  - Tags already in the file always win; suggestions only fill empty fields or tidy values.
- **Inbox layout**: a compact list (the name each track will have, its filename, one status: "4 changes", "Needs genre", "✓ Ready") with checkboxes for actions on several tracks. Clicking a track opens its **review page**: every field filled in with Tagwerk's suggestion, marked *suggested*, *your value* or as in the file; correct anything, then **Save and next ›** to work through the inbox. Corrections are stored by Tagwerk and only written to the file on import.
- **Filenames stay as they are**: writing tags and importing never rename files. (Renaming will be an opt-in feature for tracks you mark as final.)
- **Import** (v0.7, step 3): tick tracks in the inbox and press **Import**, or use **Import** on a track's page. Tagwerk writes the tags shown on the track's page (your values, else its suggestions), then moves the file into the library: **copy, verify, delete the original**. The folder is the main genre (`Drum & Bass/`, `House/`, or `_Unsorted/`); the **filename stays exactly the same**. A file that already exists in the library is never overwritten: the track stays in the inbox with a note. Tracks need at least a title and an artist.
- **Cover art on import**: on an inbox track's page, click the cover to replace it with a JPEG or PNG, or remove it (same as on the edit page). The choice is written into the file on import; undo brings the old cover back.
- **Inbox tabs**: All · Needs help · Edited · Ready (· Unreadable), each with its count. A tab shows only those tracks (instantly, without reloading, so ticked tracks stay ticked when switching tabs), and **Save and next ›** on a track's page stays within the tab.
- Imports appear in **History & undo**: undo restores the old tags and moves the file back into the inbox.
- **Navidrome rescan** (v0.7, step 4): optional **Navidrome URL / User / Password** in the Unraid template. After every apply, import and undo, Tagwerk asks Navidrome to rescan (Subsonic API `startScan`; the user needs admin rights), so changes show up there right away. **Settings → Navidrome** shows the last result and has **Test connection** and **Rescan now**. The password is only sent as a salted token. Tested against Navidrome 0.64.2.
- A built-in **genre map** of spelling variants and subgenres (Drum & Bass, House, Techno, Trance, …). Lookups are simple dictionary checks: no database, no network.

### Changed
- **Saving edits returns you to where you were**, e.g. the filtered track list, with a short note ("Saved 3 pending changes · Review →") instead of jumping to the Changes page. Editing one track after another is now quick.
- "← Back" links on the track and edit pages lead to the page you came from (keeping filters), without relying on the browser history.
- Header on tablets and phones (below 800px): Inbox, Changes and Settings move into the menu, which shows how many items wait. On narrow phones the logo appears without the word "Tagwerk".

### Fixed
- Inbox: the **Import** button could stay greyed out, because opening the page starts a quick check of the import folder. That check no longer blocks the button; an import waits for it to finish.
- **Removing a comment didn't work** for MP3/WAV/AIFF files that contain extra comment copies (e.g. "ID3v1 Comment", left by older taggers): Tagwerk showed them, but only removed the main one. Reading and writing now use the same rule, so every copy is removed (and restored on undo). iTunes' hidden technical comments stay untouched.
- Track list: **"Edit selected"** stayed greyed out after ticking tracks, so several tracks could only be edited with "Edit all matching". The script was accidentally placed inside the page title.

## [0.6.1] - 2026-10-04

### Added
- **Cover art editing**: on the edit page, click the cover (a pen appears on hover) to replace it with a JPEG or PNG, or remove it — for one track or many at once. The cover is written into the file (all 7 formats), shown on the review page, and can be undone like any other change.
- Uploaded covers and the old covers kept for undo are stored in `/config/images` (each image once, even if a whole album uses it).

### Changed
- The **Save** button on the edit page stays at the bottom of the window while scrolling; fields keep clear of it.
- Edit page: the info box at the top is gone; the save bar says that nothing is written yet.
- Track page: the other mode's fields ("Album and more" / "DJ fields") fold out inside the main card, and the MusicBrainz IDs moved behind an **ⓘ** button at the top right (with a marker when an ID is invalid).
- The header no longer has a "Dashboard" link: the Tagwerk logo leads there.

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

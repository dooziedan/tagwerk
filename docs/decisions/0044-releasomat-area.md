# 0044: The Releasomat area: a discovery folder inside the library, adopted into it by click
Date: 2026-10-24 · Status: Accepted (owner's decisions 2026-10-24/25)

## Context
Releasomat, the owner's companion app, turns playlists from Apple Music, ListenBrainz, Beatport and
others into Navidrome playlists. Tracks Navidrome doesn't have yet it downloads (Soulseek through
slskd, or YouTube) into **its own folder inside the music library**: `/mnt/user/music/Releasomat`,
which Tagwerk sees as `/music/Releasomat`. Releasomat writes normal tags only: title, artist, album,
ISRC, the MusicBrainz recording ID (when known) and the cover; no note about where a file came from.

Today Tagwerk scans that folder like every other library folder. So the downloads are counted on
Home and Statistics, analysed (BPM, key, loudness), checked (missing tags, ReplayGain, Fix IDs),
grouped as duplicates, offered for the trash, final marks and renaming, and "Releasomat" even counts
as an existing genre folder for imports. If one of those actions moves or removes a file,
Releasomat's next refresh downloads it again. If Apply writes tags into it, Tagwerk has edited a file
that isn't part of the owner's curated library.

On 2026-10-24 the owner decided (Releasomat [ADR 0009](https://github.com/dooziedan/releasomat/blob/main/docs/decisions/0009-tagwerk-integration.md),
"Weg 2"):
- Releasomat's folder is a **discovery area**, not part of the curated DJ library.
- A track enters the library only when the owner **adopts** it in Tagwerk, by click. It then goes
  through the normal import inbox ([ADR 0007](0007-import-inbox.md)).
- A Releasomat track the owner throws away is marked **Don't like** in Releasomat and never
  downloaded again.

And on 2026-10-25, for Tagwerk:
- The folder leaves the library after **one confirming click** in Settings, after a pre-check that
  shows what leaves Tagwerk's lists.
- The Releasomat page offers **Adopt and Delete**. Delete asks Releasomat to delete the file;
  Tagwerk itself never deletes area files.
- **Give back** (an adopted file back into the area) comes later.
- **The integration is optional.** Tagwerk works in full without Releasomat, and Releasomat
  without Tagwerk; nobody is forced to run both. Without `RELEASOMAT_FOLDER`, `RELEASOMAT_URL`
  and a confirmed folder, Tagwerk works exactly as before and **nothing mentions Releasomat**: no
  Settings section, no menu entry, no notification switch, no warning or hint that it isn't set
  up. Only Tagwerk calls Releasomat, never the other way round; Releasomat not answering never
  stops a scan, an import or any other part of Tagwerk.

Defaults where the owner didn't decide: Work → Releasomat in the menu without a number, no line on
Home and no notification for new downloads, for now.

This record decides Tagwerk's side. The contract between the two apps is Releasomat's ADR 0009
(Accepted); what Tagwerk relies on is summed up under [Contract](#contract).

## Decision

### The area is not library: skipped by the library scan, listed from its own table
Two ways were weighed:

| | **A: scanned into `track`, flagged** | **B: skipped by the library scan, own table** |
|---|---|---|
| Keeping it out | every query in about 40 modules needs `not area` (lists, Home, Statistics, Tagwerk's work, checks, tools, analysis, loudness, duplicates, final, convert, Changes, the player…) | nothing to change: the rows don't exist |
| A missed spot | Tagwerk acts on a Releasomat file, maybe **writes tags** into it | impossible: there is no row to act on |
| Dashboard rule | every number and its list must exclude the area; the test only catches the dashboard | numbers stay as they are; the test just gets an area folder in its fixture |
| CPU | analysis and loudness run on every download unless excluded too | none for the area |
| Releasomat page | reads `track` | reads a small `releasomatfile` table (path, format, bitrate, sample rate, bit depth, length, size, title, artist, album, MusicBrainz ID, cover yes/no) |
| Existing rows | stay, with their analysis | removed on the first scan after the switch (see Transition) |
| Precedent | none | `InboxTrack`: "kept apart from `Track` on purpose" (ADR 0007) |

**Chosen: B.** Safety comes from the data model, not from remembering a condition in every query:
a file without a `track` row can't be edited, applied, renamed, moved, trashed or counted. The
cost is one small table and a reader like `scan_inbox` (new or changed files only, no raw tags, no
analysis), and the area's files lose the track page and edit page, which is intended: they aren't
the owner's library.

Considered and left out: a marker file that Releasomat writes into its folder (the scanner skips
any folder containing it). It needs no folder name, but the folder name plus the check against
Releasomat's file list (below) already proves the folder, and a marker the owner deletes by
accident would silently turn the downloads back into library tracks.

### Where the area is, and switching it on
- **Settings**, all container variables (Unraid template), shown read-only on Settings like Navidrome:
  `RELEASOMAT_URL` (Releasomat's address by host IP, reachable from the browser too, since playlist
  links point there), `RELEASOMAT_API_KEY` (Releasomat's `INTEGRATION_API_KEY`, masked, never shown,
  logged or sent to the browser) and `RELEASOMAT_FOLDER` (optional manual folder).
- **The folder** is `RELEASOMAT_FOLDER` when set, else what Releasomat reports (`GET
  /api/integration/info`). The reported name is stored (`appsetting`), so scans still know the area
  when Releasomat is down.
- **Checked before use:** a folder inside `/music` (nested is fine: `Downloads/Releasomat`), that
  exists, isn't hidden (`.` or `@`), isn't inside `_Unsorted`, isn't the whole library and isn't a
  ticked main genre.
  Releasomat's own file list confirms it: "12 of 12 Releasomat files found in /music/Releasomat". (The
  name is relative to Navidrome's music folder; if Tagwerk's `/music` maps somewhere else, this check
  fails and the owner sets `RELEASOMAT_FOLDER`.)
- **Switched on once by the owner** in Settings → Releasomat with **Keep this folder out of the
  library**, after a pre-check that says what leaves the library lists: tracks, pending changes,
  final marks, duplicate groups, library-trash entries from that folder. Only the confirmed folder
  is skipped. If Releasomat later reports another folder, Settings asks again (the old one stays
  skipped until then). **Treat it as library again** undoes the switch: the next scan reads the
  files back in.
- Without Releasomat configured nothing changes: Tagwerk works as today, and Settings has no
  Releasomat section (it appears once `RELEASOMAT_FOLDER` or `RELEASOMAT_URL` is set, or a
  folder is kept out). The notification switch for the Releasomat topic is hidden the same way
  and keeps its value while hidden.

### Every place, decided
| Place | Today | With this decision |
|---|---|---|
| Library scan (`scanner.find_files`, `scan_library`) | reads the area | skips the confirmed folder (a `skip` argument); rows already in it are removed once, counted on their own (`progress.left_for_area`) and reported |
| Area check (new) | | reads the area into `releasomatfile`: after each library scan, and when the Releasomat page opens (like the inbox check, at most every 10 s) |
| Track list, filters, search, artists, albums | include the area | excluded: no rows |
| Home, Statistics, Tagwerk's work, Tag fields | count the area | excluded: no rows; no Releasomat number on Home for now (default) |
| Changes, Apply; Fix IDs, ReplayGain, Mix names, Genre spellings, Look up online, Convert | may stage or write changes to area files (sure BPM/key from the audio are staged on their own) | excluded: no rows; pending changes on area rows go with the rows (reported) |
| Audio analysis, loudness | analyse downloads | excluded; the Releasomat page shows BPM/key from the playlist source when Releasomat sends them |
| Duplicates page, library trash | area copies are grouped and can be trashed | excluded; the Releasomat page uses `LibraryIndex.matches` read-only for "In your library" |
| Final check, Mark as final, renaming | area files can be marked and renamed | excluded: no rows |
| Genre folders and import destinations (`naming.existing_folders` for import, convert, folders and the wizard; `importer.plan`; `folders.proposals`) | "Releasomat" counts as an existing genre folder; an import or a folder move could land in the area | `existing_folders` leaves the area out; a destination inside the area is refused (import: a problem "would land in the Releasomat folder"; folders: no proposal) |
| Better copies (`upgrade.py`) | an inbox file could replace an area file | excluded (library copies are `track` rows); the Releasomat page reuses `upgrade.better()` for "Better sound than your copy" |
| Library-trash Restore (`duplicates.restore_copy`) | reads the file back in as a library track | a file whose old path is inside the area goes back there but isn't read into the library |
| Undo (`undo.py`) | | an entry whose file is now inside the area is refused ("this file is in the Releasomat folder now"), so Tagwerk never writes there |
| Inbox | | adopted files arrive in `/import/Releasomat/…` with a **From Releasomat** chip and their playlists (loaded in `inbox.load_known`, [ADR 0038](0038-fast-inbox.md)); everything else as usual: lookup, BPM/key, duplicates, better copies, review or automatic import, secret mark |
| Inbox trash (`routes/inbox.py`) | | an adopted file thrown away: Releasomat is told (*discarded*); restored within 30 days: told again (*restored*) |
| Navidrome | rescans the whole library | unchanged: Navidrome must see the area for Releasomat's playlists. No rescan after Adopt (the file isn't library yet); the import rescans as before |
| Player | plays area files as library tracks | read-only audio routes for area files (▶ on the Releasomat page), same helpers |
| Notifications | | a topic **Releasomat** (on): the one-time "N tracks left the library", a notice Releasomat hasn't taken for a day, the folder changed or vanished. Nothing for new downloads |
| Menu | | Work → **Releasomat** after Inbox, without a number, only when Releasomat is configured |

### The Releasomat page (`/releasomat`)
- **Page head**: "Releasomat", eyebrow "Discovery area · not in your library"; a notice when
  Releasomat doesn't answer ("Adopt is off until it's back; files are shown as Tagwerk reads them")
  or `/import` is missing.
- **Headline tiles**: files in the area, not in your library yet, better sound than your copy, low
  quality.
- **Tabs**: All · Not in library · In your library · Better sound · Low quality · Adopted. A playlist
  filter and a search box. Paged (100 a page, filtered on the server: the area can grow to thousands
  of files, unlike the inbox).
- **One row per file**, newest download first, DJ things first (ADR 0024): ▶, cover (planet when
  none), artist – title, **audio quality** (format, bitrate or bit depth/sample rate; lossy below
  320 kbps marked in `--tw-warn` with the word), length, BPM and key **from the playlist source**
  when Releasomat knows them ("from Beatport"), the Releasomat playlists containing it (chips linking
  to Releasomat), **In your library** (`--tw-check`, link to the library copy and why: same
  recording / same artist and title) or **Better sound** (`--tw-ok`: "FLAC, your copy MP3 192
  kbps"), and **Adopt** and **Delete** (quiet buttons per row). Shift-click ticking
  (`data-range-select`); the bar for ticked rows has the gold **Adopt N tracks** and a quiet
  **Delete N tracks**.
- **Delete** asks Releasomat to delete the file (`POST /api/integration/delete`): Releasomat runs its
  own owner-delete (only files it downloaded, only in its folder) and marks the track Don't like.
  Tagwerk touches no file. A confirmation names the files and the playlists that contain them:
  "Releasomat deletes these 2 files and won't download them again. Still in: Weekly Exploration."
  Offered only when Releasomat answers. Afterwards Tagwerk reads those paths again and drops the rows
  of files that are gone; a file Releasomat refused stays, with its reason. Handy for files that are
  already in the library.
- **Adopted** tab: what was adopted, where each file is now (in the Inbox / in the library / thrown
  away / given back / gone), derived from the inbox, the History and the adoption record. This tab is
  the record of adoptions, as the trash is for trash moves ([ADR 0023](0023-library-trash.md)): Adopt
  doesn't write tags, so it doesn't go into the History. Deleted files aren't listed: Releasomat
  keeps them as Don't like, with Undo on its playlist page.
- Which playlists contain a file comes from `GET /api/integration/files` when the page is built
  (5 s timeout, kept for a minute); format, quality and "in your library" come from Tagwerk's own
  table, so the page works without Releasomat.
- Look per [design.md](../design.md): glass page head, `.kpi` tiles, chips and status pills, colour
  tokens only, no `color-mix()`, cards come in on page change, no big effect for Adopt (big effects
  stay with Convert and Apply). Works on phones (rows stack; the ticked-rows bar above the play bar).
  Checked with `scripts/screenshots.py`.

### Adopt
1. **Before the click**: Adopt is offered only when Releasomat answers, the area is confirmed and
   `/import` exists and is writable. **Without an import folder** the page says "Adopting moves tracks
   into the import inbox: map /import in the container template" and nothing happens. Tagwerk never
   adopts straight into the library: that would skip identification, BPM/key, the duplicate check
   and the review the owner chose the inbox for.
2. **A job** sharing the job lock: never during a scan, import or write; the quick inbox check
   finishes first.
3. **Checked per file, nothing changed yet**: still there, the same size and time as at the area
   check, unchanged for 2 minutes (`importer.STABLE_AFTER`: a guard for files copied in by hand;
   Releasomat's own downloads appear in one step), Tagwerk may remove files in its folder (both
   containers run with the same PUID/PGID), and the inbox path `/import/Releasomat/<path in the
   area>` is free (never overwritten).
4. **Releasomat first**: one `POST /api/integration/adopt` for every file that passed. No answer,
   a timeout or an error: **nothing moves**, and the page says why ("Releasomat didn't answer at
   http://…: nothing was adopted"). Files Releasomat refuses are listed with its reason.
5. **Then the move**, with the importer's `move_file`: copy to a hidden `.name.tagwerk-part`, compare
   both SHA-256 sums, rename, and only then remove the original. If a move fails, the original stays
   where it was and Tagwerk tells Releasomat the file came back (*returned*, why `move_failed`;
   queued if Releasomat is gone in that second). If only removing the original fails, Tagwerk
   removes its own fresh inbox copy (identical by checksum), so the file is never in both places.
6. **After**: the file is read into the inbox list at once (`inbox.add_file`), the adoption is
   stored (area path, inbox path, Releasomat's file id, playlists, size) and the online lookup and
   analysis start as after an inbox check. A toast says "Adopted 3 tracks. They wait in the Inbox".
7. **From there the inbox decides**: import (by hand or automatic), better copy, or the trash.
   Releasomat's tags stay unless the owner changes them on the review page: the import only fills
   empty ID fields, Fix IDs keeps real MusicBrainz IDs, and ISRC isn't a Tagwerk field, so it isn't
   touched.

### Thrown away, restored, given back
- **Thrown away**: when the owner moves an adopted inbox file to the inbox trash, Tagwerk tells
  Releasomat (`POST /api/integration/discarded`), which marks it Don't like. The trash confirmation
  says so: "1 of these came from Releasomat: it will be marked Don't like there and not downloaded
  again." Restored from the inbox trash within 30 days: Tagwerk tells Releasomat (*restored*). A
  file removed from the inbox by hand isn't reported: Tagwerk can't tell why it went.
- **Notices are kept until Releasomat takes them** (`releasomatadoption.notice`): sent right after
  the trash action, outside the job lock, and retried by the regular check every few minutes. Not
  taken after a day: a Releasomat notification (solved when it goes through).
- **Give back** (later, owner 2026-10-25): on the Adopted tab, while the file is still in the inbox
  and unchanged, the owner can send it back to its old place in the area (copy, verify, remove;
  never over an existing file), and Releasomat is told (*returned*, why `given_back`). For a
  mis-click, without marking a track Don't like.

### The Releasomat client (`app/releasomat.py`)
Like `app/navidrome.py`: standard library HTTP, Tagwerk's User-Agent, JSON, short timeouts (5 s for
`info` and `files`, which pages wait for; 15 s for the POSTs), no retries of POSTs inside one call
(the regular check retries notices). Calls: `info`, `files`, `adopt`, `returned`, `discarded`,
`restored`, `delete`. The key goes only into an `Authorization: Bearer` header, never into a URL.
Logs name the endpoint and status, never headers or the key. Answers in plain language: not set up,
not answering, the integration switched off in Releasomat (403: no `INTEGRATION_API_KEY` there), key
wrong (401), too old for the integration (404), newer than this Tagwerk understands
(`integration_api` major), refused with Releasomat's reason.
The last result is shown in Settings with a **Test** button. It isn't a metadata source
([ADR 0014](0014-online-identification.md)), so it doesn't live in `app/sources/`. Tests never go
online: saved answers in `tests/fixtures/online/releasomat_*.json`.

### Rules amended
CLAUDE.md gets these changes when this record is accepted:
- New rule: **The Releasomat area is not library** ([ADR 0044](decisions/0044-releasomat-area.md)).
  The confirmed area folder is skipped by the library scan; Tagwerk never tags, renames, trashes or
  deletes files there and never moves files into it. Files leave it only by the owner's **Adopt**
  and come back only by **Give back** (`app/adopt.py`). The page's **Delete** asks Releasomat, which
  deletes the file itself.
- "Tagwerk never deletes library files on its own" gets: removing an area file after its verified
  copy reached the inbox is part of the owner's Adopt, a move like the import's, not a deletion.
- The list of modules that move files gets `app/adopt.py` (area ↔ inbox only). `app/writer.py`'s
  list doesn't change: Adopt writes no tags.

## Consequences
- The curated library and its numbers no longer include downloads the owner hasn't chosen. Nothing
  in Tagwerk can change a Releasomat file except Adopt and Give back; Delete is done by Releasomat.
- Area files have no track page, edit page, analysis or History; the Releasomat page is all Tagwerk
  shows about them. Tags, BPM and key are worked on after adopting, in the inbox.
- Adopting and deleting depend on Releasomat answering. That is on purpose: a silent adoption would
  make Releasomat download the file again.
- Inbox files carry no tag that says they came from Releasomat; Tagwerk knows it from its adoption
  record only.
- Two new tables (`releasomatfile`, `releasomatadoption`) and a short Settings card; the dashboard
  rule and the inbox's query test keep working unchanged.

## Risks
- **The owner's existing database already holds the downloads as library tracks.** The first scan
  after the switch removes those rows and, with them (cascade), their analysis, loudness, pending
  changes, duplicate links, final and secret marks and online results; History entries keep their
  paths but lose the track link. The pre-check in Settings shows the numbers before the click, and
  the scan reports them once. Tags Tagwerk may already have written into downloads (an Apply that
  included staged BPM/key) stay in the files; the History shows which. A library copy the owner
  trashed in favour of a download (Duplicates page) would leave the library without that song:
  the pre-check lists duplicate groups whose kept copy is in the area.
- **Navidrome IDs and play counts.** Adopt and import give the song a new path, sometimes new tags,
  and the file is out of Navidrome's sight while it waits in the inbox: meanwhile it is missing from
  the Releasomat playlist. Recent Navidrome versions can reconnect a missing song to a file that
  comes back elsewhere by its persistent ID, which by default uses the MusicBrainz recording ID;
  worth checking on the owner's version. Tagwerk keeps Releasomat's MusicBrainz ID, which gives that
  the best chance. If Navidrome doesn't reconnect, Releasomat finds the library copy on its next
  refresh (ADR 0009) and plays or stars made on the download are lost.
- **Files arriving while Tagwerk reads.** Releasomat writes downloads under a hidden name and renames
  them when complete, so its own files never appear half-written. Files copied into the area by hand
  can: the area check lists them as unreadable or short and reads them again once they change, and
  Adopt only takes files unchanged for 2 minutes and still matching the area check.
- **Permissions.** Adopt removes the original from Releasomat's folder, so both containers must run
  with the same PUID/PGID (Unraid's 99/100 by default). Tagwerk checks this before asking Releasomat.
- **A wrong folder** (a typo in `RELEASOMAT_FOLDER`) would hide part of the real library. The checks,
  the file-list match and the one-time confirmation with its numbers guard against it.
- **Import rules pointing into the area**: an artist or label called "Releasomat" in a custom folder
  pattern. Refused as an import problem, never filed there.

## Contract
The integration API is specified in Releasomat's
[ADR 0009](https://github.com/dooziedan/releasomat/blob/main/docs/decisions/0009-tagwerk-integration.md)
(Accepted, version 1). What Tagwerk relies on:
- `GET /api/integration/info` → `app`, `version`, `integration_api` (Tagwerk understands 1; unknown
  fields are ignored), `folder`.
- `GET /api/integration/files` → `folder` and the files in the area now: `id`, `path`, `size`,
  `downloaded_at`, `downloader`, `format`, `bitrate`, `wanted` (artist, title, album, duration,
  ISRC, `mbid`, and `bpm` and `key` when the playlist source has them; genre and label once a
  source stores them), `playlists` (`id`, `name`, `url` of the playlist's page in Releasomat).
- `POST adopt`, `returned` (`why`: `move_failed` or `given_back`), `discarded`, `restored`, `delete`:
  `{"files": [{"path", "size", "id"?}]}` in (`returned` also `"why"` next to `files`); out
  `{"integration_api": 1, "files": [...]}`, one entry per file in the order sent: `asked`, `ok`,
  `changed`, `reason` (plain words, when not ok), `id`, `path`, `status`. Repeating a call that
  went through answers `ok` again, so Tagwerk may retry. `adopt` and `delete` refuse a file whose
  size differs from the one sent; `delete` refuses a file sent without its size.
- Files are named by their path inside the area (`/`, Unicode NFC) plus their size; answers carry
  Releasomat's file `id`, which Tagwerk stores for later notices.
- The key only in `Authorization: Bearer …`; 403 `integration_off` means the integration is
  switched off in Releasomat, 401 `wrong_key` a missing or wrong key. Every error has the shape
  `{"integration_api": 1, "error": "<code>", "message": "<plain words>"}` (also `bad_request`
  with 422, `not_found`, `method_not_allowed`).
- After `adopt` said yes, Releasomat leaves that path alone. `delete` is the only call that makes
  Releasomat touch a file, with its own owner-delete.
- Downloads appear in one step (hidden name, then renamed).
- Either app can be updated first: without the integration API, Tagwerk's page lists files
  read-only; keeping the folder out (step 1) needs nothing from Releasomat.

## Implementation sketch

### Modules
| File | What |
|---|---|
| `app/config.py` | `releasomat_url`, `releasomat_api_key`, `releasomat_folder` |
| `app/area.py` (new) | The area: the active folder (confirmed preference; reported name stored), `check_folder()`, `contains(rel)`, `area_dir(settings, session)`; `sync(paths=None)` keeps `releasomatfile` in step with the folder, or with a few of its paths (like `inbox.scan_inbox`, via `scanner.find_files` and `tags.read_file`); adoption records: `adopted()`, `note_discarded()`, `note_restored()`, `state()` (derived), `pending_notices()`. Low in the import order: imports `scanner`, `tags`, `models`, `preferences`, never `adopt` |
| `app/releasomat.py` (new) | The client: `configured()`, `info()`, `files()`, `adopt()`, `returned()`, `discarded()`, `restored()`, `delete()`, `ReleasomatError`, `last` (for Settings) |
| `app/adopt.py` (new) | The owner's actions on area files: `check()` (what may be adopted or deleted, and why not), `adopt_files()` (the job), `delete_files()` (asks Releasomat, then `area.sync()` for those paths; touches no file), `give_back()` (later), `send_notices()`. Imports `area`, `releasomat`, `importer.move_file`, `inbox.add_file`, `notifications`; nothing imports it except routes, `jobs` and `reminders` ([ADR 0040](0040-no-import-circles.md)) |
| `app/scanner.py` | `find_files(music_dir, skip=())`; `scan_library(…, skip=())` removes rows inside a skipped folder and counts them (`ScanProgress.left_for_area`) |
| `app/naming.py` | `existing_folders(music_dir, skip=())` |
| `app/importer.py` | `plan()` adds a problem for a destination inside the area |
| `app/folders.py` | no proposal for a folder inside the area |
| `app/duplicates.py` | `restore_copy()` doesn't read a restored area path into the library; `LibraryIndex.matches()` accepts the area file and folder (it uses only `size`, `path`, `mb_trackid`, `duration`; rename `import_dir` to `base_dir`) |
| `app/undo.py` | refuse entries whose file is inside the area |
| `app/jobs.py` | the scan job passes the area to the scanner and runs `area.sync()` after it; an area-check job (on opening the page); `JobRunner.adopt()`. Delete needs no job: it only asks Releasomat and reads a few paths again |
| `app/reminders.py` | `adopt.send_notices()` in the regular loop; the "not taken for a day" notification |
| `app/topics.py` | topic `releasomat` (on) |
| `app/inbox.py` | `load_known()` also loads adoption marks (From Releasomat chip, playlists) |
| `app/routes/releasomat.py` (new) | the page and its API |
| `app/routes/inbox.py` | `_move_to_trash()` → `area.note_discarded()`, `_restore()` → `area.note_restored()`, then `adopt.send_notices()` in a thread; the trash confirmation names adopted files |
| `app/routes/player.py` | `/releasomat/{id}/audio` and `/audio.mp3`, root = the area |
| `app/routes/settings.py` | the Releasomat card: Test, the pre-check, confirm / treat as library again |

### Model and migration
One migration, two new tables (no new columns on existing tables):
- `releasomatfile`: `id`, `path` (unique, relative to the area), `format`, `size`, `mtime`,
  `duration`, `bitrate`, `sample_rate`, `bits_per_sample`, `title`, `artist`, `album`, `mb_trackid`,
  `has_cover`, `error`, `found_at`, `scanned_at`.
- `releasomatadoption`: `id`, `area_path`, `inbox_path` (indexed, relative to `IMPORT_DIR`),
  `releasomat_id`, `size`, `title`, `artist`, `playlists` (JSON names), `adopted_at`, `state`
  (`adopted`, `discarded`, `returned`; "in the Inbox", "in the library" and "gone" are derived from
  the inbox and the History: an import or better-copy entry with `moved_from == inbox_path` applied
  after `adopted_at`, not undone), `notice` (`discarded`, `restored`, `returned` or empty: waiting to
  be sent), `notice_since`, `notice_error`.
- `appsetting`: `releasomat_area` (the confirmed folder, a preference) and the last reported folder.

### Routes
| Route | What |
|---|---|
| `GET /releasomat` | the page (`tab`, `playlist`, `q`, `page`) |
| `GET /api/releasomat/files` | the same rows as JSON |
| `POST /api/releasomat/check` | read the area now (also the page's "Check again") |
| `POST /api/releasomat/adopt` (`{"ids": […]}`), `POST /releasomat/adopt` (form) | start the adopt job; 409 with the reason when Releasomat, the area or `/import` isn't ready |
| `POST /api/releasomat/delete` (`{"ids": […]}`), `POST /releasomat/delete` (form) | ask Releasomat to delete; answers per file; 409 when Releasomat isn't answering |
| `GET /api/releasomat/adoptions` | the Adopted tab as JSON |
| `POST /api/releasomat/adoptions/{id}/give-back` | Give back (later step) |
| `GET /releasomat/{id}/audio`, `/audio.mp3`, `/cover` | play and show an area file (read-only) |
| `POST /settings/releasomat/test`, `POST /settings/releasomat/area` | Settings: test the connection; confirm the folder or treat it as library again |

### Templates
`releasomat.html` (page head, tiles, tabs, rows, ticked-rows bar, the Delete confirmation), the Releasomat card in
`settings.html`, the From Releasomat chip in `inbox.html` and `inbox_track.html`, the trash
confirmation text, the menu entry in `base.html` (side menu and phone menu), a nav icon (a telescope,
in the night-sky spirit), the Releasomat topic in Settings → Notifications.

### Settings
`RELEASOMAT_URL`, `RELEASOMAT_API_KEY` (masked) and `RELEASOMAT_FOLDER` in `unraid/tagwerk.xml` (the
template test keeps it complete), `docker-compose.yml` and `.env` examples.

### Tests
- **Scan**: area files never become tracks; existing area rows are removed once, counted and
  reported, with their final marks and pending changes; an unconfirmed folder isn't skipped; the
  empty-library guard still fires only for a really empty library.
- **Numbers**: `test_every_dashboard_number_matches_its_track_list` again with area files in the
  fixture library: the same numbers as without them.
- **Guards**: `existing_folders` leaves the area out; import, folder proposals and undo never land in
  or write to the area; a library-trash Restore into the area isn't read in.
- **Folder checks**: empty, `.`, `..`, absolute, hidden, `_Unsorted`, a ticked main genre are
  refused; nested folders work; the file-list match.
- **Area check**: only new or changed files are read; unreadable files are listed; recent files
  aren't adoptable.
- **Client** (saved answers, fake `urlopen` as in `test_navidrome.py`): info, files, a mixed adopt
  answer, a mixed delete answer, 401, 403, 404, a timeout, an unknown `integration_api`; the key only in the header and never in
  the log (`caplog`); the User-Agent.
- **Adopt**: the file ends up in the inbox and the original is gone; Releasomat not answering or
  refusing: nothing moves; a failed copy (checksum, full disk): the original stays and *returned* is
  sent or queued; removing the original fails: the inbox copy goes, the original stays, *returned*;
  no `/import`, a taken inbox path or no right to remove files in the area: refused before
  Releasomat is asked; a file changed since the check: refused; never during another job.
- **Delete**: Releasomat says ok and the file is gone: its row goes; Releasomat refuses or doesn't
  answer: nothing changes and the reason is shown; ok but the file still there: the row stays;
  Tagwerk never removes an area file itself (a test fails on any unlink inside the area).
- **Notices**: an adopted file to the inbox trash sends *discarded*; Releasomat down: kept, retried,
  a notification after a day, solved when sent; Restore sends *restored* (or drops an unsent
  *discarded*); other inbox files send nothing.
- **Derived state**: Inbox → library (import, better copy) → Inbox again (undo) → gone (removed by
  hand).
- **Pages**: the Releasomat page's queries don't grow with the number of files (like ADR 0038's
  test), the Inbox's still don't; the page works with Releasomat down and without `/import`; the
  audio route refuses paths outside the area.
- **Migrations**: `test_migrations_match_models` and the upgrade-through-every-migration test with
  rows in both new tables; `tests/test_imports.py` (no circles).
- **Screens**: `scripts/screenshots.py` with the Releasomat page (Chromium, Firefox, WebKit; desktop
  and phone).

### Order of work
Small PRs, each with its CHANGELOG entry, docs (`architecture.md`, `roadmap.md`) and, for UI,
screenshots:
1. **Keep the folder out** (needs nothing from Releasomat): `RELEASOMAT_FOLDER`, `app/area.py` (folder
   and checks), the scanner's skip, the guards (`existing_folders`, import, folders, undo, trash
   restore), the Settings card with the pre-check and the confirm button, the one-time report, the
   CLAUDE.md rule. This alone stops Tagwerk from acting on downloads.
2. **The connection**: `app/releasomat.py`, `RELEASOMAT_URL`/`_API_KEY`, Test in Settings, the folder
   from `info` (stored), the file-list match.
3. **The Releasomat page, read-only**: `releasomatfile` and its migration, the area check, the page
   with tiles, tabs, quality, "In your library" and "Better sound", playlists, ▶, the menu entry.
4. **Delete**: `releasomat.delete()`, `adopt.delete_files()` (the module starts here), the buttons,
   the confirmation and the routes.
5. **Adopt**: `releasomatadoption` and its migration, the adopt job, the From Releasomat chip in the
   inbox, the Adopted tab.
6. **Thrown away and restored**: the inbox-trash hooks, notices kept and retried, the Releasomat
   notification topic.
7. **Give back**: later (owner, 2026-10-25).

Steps 2 to 7 need the matching parts of Releasomat's integration API; step 1 can ship first.

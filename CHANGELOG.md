# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.18.2] - 2026-10-10

### Fixed
- **No more error in the log after a double click**: clicking **Use these values** (or **Look up online**) twice quickly made the browser cancel the first request, and the log showed a long `ClientDisconnect` error. Nothing went wrong, as the second click did the work. The buttons are now locked while their request is sent, and a cancelled request is no longer logged as an error.

## [0.18.1] - 2026-10-09

### Removed
- **The "MusicBrainz IDs" setting** (Settings → Display). It came from the Collector idea. Wrong values in MusicBrainz ID fields (often Discogs numbers) are now always shown on Home and Statistics, with **Fix IDs** to repair them. Missing MusicBrainz IDs no longer appear as a "missing tags" ring on Statistics: edits and bootlegs aren't on MusicBrainz, so a missing ID isn't a problem. The track list's *Missing MusicBrainz IDs* filter is still there. The API's settings no longer include `show_musicbrainz` (sending it is ignored).

## [0.18.0] - 2026-10-09

### Added
- **Edit ReplayGain**: the edit page has a new **ReplayGain** section with track gain, track peak, album gain and album peak, for one track or many at once. Like every edit, the values become pending changes and are written only when you apply them, with undo. Navidrome uses these tags to even out the volume between tracks. Measuring ReplayGain from the audio comes in a later version.
- **All ReplayGain values are read**: Tagwerk read only the track gain so far; now it also reads the track peak, album gain and album peak, and the track page shows them. The next scan reads every track once more to pick them up.

### Fixed
- **Opus files showed no ReplayGain**: Opus keeps its gains in its own fields (`R128_TRACK_GAIN`, `R128_ALBUM_GAIN`, relative to a different reference level), which Tagwerk didn't read, so Opus tracks counted as missing ReplayGain. They are now read and written the Opus way. Opus has no peak fields, so the edit page leaves the peaks out for Opus files.

## [0.17.2] - 2026-10-09

### Changed
- **Duplicates: decide first, apply once.** **Move to trash** on the Duplicates page no longer moves the file right away (and no longer opens the trash list). The copy is marked "Goes to the trash on Apply" and you stay where you were on the page, so you can go through all your groups, take tags over and mark copies as you go. **Don't trash** takes a mark back. The marked copies move to the trash when you press Apply on the Changes page, together with the tag changes; there they show as "Move to trash" and can be unticked or discarded like any change. The trash itself works as before: restorable until you empty it.
- **Duplicates: every button brings you back to the same place.** **Use** and **Take over missing tags** used to switch to a view of that one group; now the page stays as it was (same filter, same page) and scrolls back to the group.
- API: `POST /api/duplicates/trash` now queues the copy as a pending change instead of moving it; `DELETE /api/duplicates/trash/{track_id}` takes the mark back.

## [0.17.1] - 2026-10-09

### Added
- **Mix names with capital letters**: a new **Mix names** page (linked from "Worth a look" on Home) lists every library track whose title writes the mix name in lower case, like "Rio (club remix)" or "Body (radio edit) [vip]", next to the fixed title: "Rio (Club Remix)", "Body (Radio Edit) [VIP]". Untick what you want to keep and Tagwerk creates pending changes. Nothing is written until you apply them on the Changes page; final tracks are skipped, and undo works as usual. Remixer names and words written in CAPITALS stay as they are.

### Changed
- **The inbox's mix name clean-up is more careful**: it now only capitalises brackets that name a mix (with a word like "remix", "edit", "VIP", or made only of track types like "(extended)"). "(the long road)", "(feat. dub phizix)" and "(DJ HYPE REMIX)" stay as written.

## [0.17.0] - 2026-10-09

### Added
- **Merge genre spellings**: a new **Genre spellings** page (linked from the Genres chart on Statistics) lists every genre written in more than one way, like "Drum & Bass", "Drum and Bass", "Drum And Bass" and "DnB", with the number of tracks per spelling. Pick the spelling to keep (the genre map's name is suggested) and Tagwerk creates pending changes that write it into every track spelling the genre differently. Other genres in the tag stay as they are ("Drum And Bass; Liquid" becomes "Drum & Bass; Liquid"). Nothing is written until you apply the changes; final tracks are skipped, and undo works as usual.

### Fixed
- **One genre, one bar on Statistics**: spellings of a genre that differ only in upper/lower case ("Drum and Bass", "Drum And Bass") or that your genre map lists as the same genre ("DnB", "Drum and Bass" → "Drum & Bass") were separate bars with their own percentages. They now count as one, and clicking it lists exactly those tracks. Before, the list for "Drum and Bass" already showed "Drum And Bass" tracks too, so the number and the list didn't agree. The same rule applies to the genre filter of the track list, "Set-ready by genre" and the heat map. Your tags stay as they are until you merge them.

## [0.16.0] - 2026-10-09

### Changed
- **Tagwerk is made for DJs; Collector mode is gone.** Every page shows what a DJ needs: BPM, key, genre, label, set-readiness and audio quality first. The mode setting (Settings → Display and the setup wizard's first question) and the Collector views (decades and lyrics on Statistics, the album-first edit form) are removed. Nothing in your files or tags changes.
- The progress card shows only on the page where its job started: "Writing your changes" on Changes, an import in the Inbox, an undo in History, converting on Convert, marking final on Final check and the track page. Track pages no longer show an Apply that is running.

## [0.15.1] - 2026-10-09

### Fixed
- **Applying more than 1,000 changes at once did nothing**: the list burnt, then the page stopped, and every change was still pending. The web framework refused forms with more than 1,000 fields, and each ticked change is one. Every form in Tagwerk now takes far longer lists (also the inbox's tick lists for big record-pool drops), so all 1,196 changes go through.
- **Following a long Apply is clear**: after the list burns, the page goes to the top and shows a status card: "Writing your changes… 120 of 806 files · 15%", a big progress bar and the file being written, with a note that you can leave the page. "No pending changes" no longer shows while they are being written.
- If Apply ever can't reach Tagwerk or is refused, the page no longer freezes after the burn: it comes back with a note that nothing was written, and the changes are still there to try again.

## [0.15.0] - 2026-10-08

### Added
- **A trash for duplicate copies**: on the Duplicates page, every copy except the one to keep has **Move to trash** (with a confirmation; final tracks can't be trashed). The copy leaves the library and Navidrome right away and waits in a hidden `.tagwerk-trash` folder in your music share. **Restore** puts it back; **Empty trash** removes the files for good, and only when you press it: Tagwerk never removes a library file on its own.

### Fixed
- **Apply** in a sensible order: the sparks fly, the changes are written right away while the list burns, and when both are done the page shows the result once ("Wrote 4 files", or the progress if writing takes longer). Before, the list burnt, came back while the files were written, and then disappeared. Changes that are being written are no longer shown on the Changes page at all, also with lighter effects.
- A **long list of changes** burns only the part on screen (at most about 2 seconds), never off the screen; afterwards the page scrolls back to the top, where the progress and the remaining changes are.

## [0.14.0] - 2026-10-08

### Added
- **Which copy to keep**: every group on the Duplicates page suggests the copy to keep, the one with the best sound (lossless before lossy, then sample rate, bit depth and bitrate; with the same sound, the most tags), and says why. Its column comes first. Because the best-sounding file isn't always the best-tagged one, you verify it: **Use** takes a tag or a different cover from another copy over to it, and **Take over missing tags** fills every tag it lacks where the other copies agree. Both become pending changes ("From another copy") you review and apply as usual. *Keep this one instead* picks another copy. Then delete the other copies in your file manager.

### Changed
- **Apply** now ends in stardust: the golden burst's sparks set the ticked changes alight, and the list burns away from the bottom up, sparkling, before the page moves on.
- The track page shows a little planet when a track has no cover (like Home's cards); the edit form and the setup wizard sit on glass, so no stars shine through the text.
- The **Play** button on the track and inbox pages matches the buttons next to it: as tall and bold, with the ▶ in a gold disc.
- The README shows the night-sky look (screenshots from a made-up library) and has a short **First steps** guide.

### Fixed
- **Percentages no longer round to 100 % while something is missing** (or to 0 % while something is there): 3 of 1,500 tracks without a tag shows 99 %, not 100 %. Applies to Statistics, Home's set-ready planet, Tagwerk's work and the Tag fields page.
- **A scan never empties the library** when the music folder has no audio files at all (a share that isn't mounted, a wrong path): it stops with a message and changes nothing. Before, every track was removed, with its final mark, analysis and history links.
- **Files moved or renamed outside Tagwerk keep their history**: a file that turns up under a new path with the same size and date is recognised as moved, so its added date (Library growth), final mark, analysis and history stay. The scan says how many files moved.
- Moving tracks into a new genre folder is all or nothing: if a track's `.lrc` lyrics file can't move, the track stays where it was too.

## [0.13.0] - 2026-10-08

### Added
- **Duplicates in the library**: a new **Duplicates** page (in the menu under Work) shows tracks that are in your library more than once, with their copies side by side: file and folder (with ▶ to listen), audio quality, length, size, the main tags, cover, date added and the final mark. Rows where the copies differ stand out. The copy with clearly the best sound and the one with clearly the most tags get a badge. Copies are found with the same rules as in the inbox: identical file, same MusicBrainz recording, or same artist and title (mix name included) at about the same length. Home and Statistics show how many tracks have copies, the track list has an *In the library more than once* filter, and a track page links to its copies. Tagwerk never deletes library files: delete a copy in your file manager and the next scan notices, or press **Keep them all** so that group isn't shown again.
- **CPU Cores** in the Unraid template (and `CPU_CORES`): how many CPU cores Tagwerk may use for BPM and key analysis; `0` is automatic. It replaces *Analysis Workers*; `ANALYSIS_WORKERS` still works.

### Changed
- **Settings is tidier**: a section index on the left shows how each section is set right now (e.g. "DJ · Camelot · full effects"); mode, key notation and effects are pill buttons; every section has one small Save button at its end; folder layouts are cards; the genre map is folded; the filename pattern only shows while renaming is on; online sources are cards; Navidrome shows its connection at a glance. Changing **Effects** shows the difference right away. *Run setup again* sits in the page header.
- **Notifications slide in** at the top right (across the top on phones): "Wrote 3 files", "Saved.", "A scan is running" and the like. Confirmations fade out after a few seconds, warnings stay until you close them; they go with the page, and a job's result is shown once, right after it finished.
- **New motion**: changing page no longer warps the sky; instead the new page's cards come in quickly, one after another. **Convert to AIFF** now jumps through hyperspace (shorter and snappier than before), and **Apply** sends a golden shock wave with sparks out of the button. Lighter effects and "reduce motion" turn all of it off.
- **Home's orbits** are drawn in 2D but look 3D: the moons stay round, grow and brighten in front of the planet and shrink, dim and pass behind it. Lighter on the browser than the old CSS 3D.
- The Unraid template describes what Tagwerk does today and has a **Log Level** field.

### Fixed
- **Home and Statistics were slow in big libraries**: with 20,000 tracks Home took 3.5 s and Statistics 10.7 s (a missing index on the History); now 0.2 s and 0.9 s. Working out BPM and key decisions after a scan takes 2 s instead of 7 s.
- The setup wizard no longer says final tracks are "coming in a coming version", and no longer mentions a DJ / Collector switch at the top.
- After saving **Effects**, the new look now applies without reloading the page.

## [0.12.0] - 2026-10-07

### Changed
- **A new look: the night sky.** Tagwerk now looks like a clear night: a deep black-blue sky with slowly drifting stars, indigo light for lines and charts, and gold for what you press. Inspired by Orbit Stage, with glass panels and a sidebar that shows every page, grouped into Library, Work and System (a floating glass bar with a menu on phones). Page headers are glass panels with a planet rising at the bottom edge; Home greets you, shows set-ready as a planet with orbits and recently added tracks as cover cards (tracks without art get their own little planet); Statistics shows missing tags as rings; the track page has a deck-style readout of BPM, key, length and format. Bars glow like thin beams, one colour per chart. Big page titles use the Orbitron font; everything you read stays in Inter.
- **Settings → Effects** replaces Theme and Appearance: Full, or Lighter (no blur, drifting stars or glow) for weak devices. Calm, Pop and light mode are gone. "Reduce motion" in your system gives a still sky.
- The key wheel keeps the standard Camelot colours; empty keys are now dark instead of grey.
- New logo colours (the same tag, in indigo) for the favicon, Apple touch icon and Unraid icon.

## [0.11.0] - 2026-10-07

### Added
- **Tagwerk's work** on Statistics shows what Tagwerk has done for your library, counted from the History (undone changes don't count): tag values written, tracks improved, imported, converted to AIFF, marked final and genre folders created; per field how many values were filled in, corrected or removed; files changed per month; and (DJ mode) how many tracks were set-ready before Tagwerk's first change and now. Home has a one-line summary linking to it.
- Tagwerk now records **where each changed value came from**: you, the audio, online, the filename, a clean-up, Fix IDs or the private-data removal. The Changes page and the History show it under the field name, and Tagwerk's work shows the share of each. Changes applied before this version count as "source unknown".

- **Tick the changes to apply** on the Changes page: every pending change has a tick box (all ticked to start with, one box per track for all its changes, plus Tick all / Untick all). **Apply** and **Discard** only act on the ticked changes; the others stay pending. The API takes `change_ids` too.


### Changed
- **Library growth** on Statistics shows tracks added per month and per year side by side, both as column charts.
- When the genre tag makes Tagwerk pick a BPM that isn't half or double what the audio hears best (e.g. 116.7 for a 174 drum & bass remix still tagged "Trance"), **From the audio** now says so with a warning and suggests correcting the genre, instead of a short note.

## [0.10.1] - 2026-10-07

### Changed
- The **Home** link in the menu is gone: the Tagwerk logo leads to Home.

### Fixed
- **Analyse BPM & key** for ticked tracks seemed to do nothing when they were analysed before: they were skipped without a word. Ticked tracks are now always analysed again (**Analyse all** still skips tracks that have a result), and the track list says what the last analysis did, e.g. "47 tracks analysed, 3 skipped".
- While the play bar is open, the **Save** buttons on edit pages (track, inbox review), the setup wizard's buttons, the inbox's selection bar and short notices sit above the player instead of under it.

## [0.10.0] - 2026-10-07

### Added
- **Home**, the page Tagwerk opens with, shows what needs you: inbox tracks ready to import or needing help, pending changes, running jobs, things worth a look (BPM at half or double time, keys that differ from the audio, wrong MusicBrainz IDs, private data such as Traktor's, tracks not set-ready), the 10 most recently added tracks (playable), and headline numbers (tracks, playing time, set-ready share, added this month).
- **Statistics** (Library menu) has the charts that used to be on the start page, plus:
  - a **heat map** of any two of key, tempo, release year, year added, genre and format (it opens on key × tempo; ⇄ swaps rows and columns), every cell opening its tracks,
  - **library growth**: tracks added per month and per year,
  - **set-ready by genre** (title, artist, genre, BPM, key and cover tagged),
  - **track length** (radio edits vs extended mixes), **top labels** and **top artists**.
- Track list filters for release year, year or month added, length, label and set-ready.
- Tagwerk remembers when each track joined the library: the import for tracks imported from the inbox, otherwise the file's date when it was first scanned. Existing tracks get the best date the database knows.
- **History** has pages (50 entries each); older entries were not reachable before.

### Changed
- **BPM and key analysis uses all CPU cores** the container may use: several tracks at once (7 tracks took 12 s instead of 52 s on 12 cores), each still with low priority. Limit it with `cpus:` in docker-compose, `--cpus` / CPU pinning on Unraid, or set **Analysis Workers** (`ANALYSIS_WORKERS`) to a fixed number. With little memory, fewer run at once.
- **Clearer navigation**: the menu has **Home**, and the entry of the page you're on is highlighted (Library for its pages, also inside the open Library menu).

### Fixed
- The README describes the current version (it still said v0.6).
- **Final tracks** no longer show up under *BPM probably half or double time*, *BPM differs from the audio* and *Key differs from the audio*: you checked their tags, so they stand. Their page shows the audio's values without a **Use** button.

## [0.9.0] - 2026-10-06

### Added
- **BPM and key from the audio**: Tagwerk measures them itself, made for bass-heavy music like drum & bass (fine frequency steps for sub-bass notes, an exact tempo to 0.05 BPM instead of steps of about 1 BPM). Inbox tracks are analysed after every inbox check; library tracks from their page (**Analyse**), for ticked tracks, or for all tracks matching the list's filters (**Analyse all**), 5-10 seconds per track in the background with low priority, so pages stay fast. **Stop** ends a long run.
- Whether a track is 87 or 174 BPM is settled with its **genre** (drum & bass is 160-185), the **filename** and **online sources** (Deezer); a value is *sure* only when the methods agree or something confirms it, otherwise *check*. Every result says why.
- **Empty BPM and key** get filled: sure values become pending changes for library tracks and suggestions for inbox tracks. **Tags that differ** are only pointed out: the track page's new **From the audio** box (with **Use 174**), and the track list and dashboard: *BPM probably half or double time*, *BPM differs from the audio*, *Key differs from the audio*, *Not analysed yet*.
- **Fix IDs** for MusicBrainz ID fields that hold something else (often Discogs numbers): on the track page, which now lists each wrong value, or for all such tracks from the dashboard's link. Real MusicBrainz IDs stay, Discogs numbers and links move to their own fields (**Discogs release ID** `DISCOGS_RELEASE_ID`, **Discogs artist ID** `DISCOGS_ARTIST_ID`), anything else is removed, as pending changes you can undo.
- Discogs IDs are read and shown in the track page's ID panel. The next scan re-reads every file once for them.

### Changed
- Automatic imports wait until a track's BPM and key were measured (right after the inbox check).
- The Docker image includes Essentia for the analysis (about 150 MB bigger).

## [0.8.4] - 2026-10-05

### Added
- **Remove private data from files**: on a private field's page under Tag fields (e.g. `PRIV:TRAKTOR4`, Traktor's waveform, beat grid and cue points), **Remove from all files** creates pending changes; you apply them on the Changes page like any edit, and **Undo** puts the data back exactly. Tags, cover art and other programs' data stay untouched; final tracks are skipped.
- **Tag fields** points out Traktor data ("Traktor data in 1,234 files") with a link to remove it.
- **Remove Traktor data on import** (Settings → Import, off by default): Traktor's data is removed from MP3, WAV and AIFF files while they are imported, also with automatic imports. Undoing the import puts it back.

## [0.8.3] - 2026-10-05

### Fixed
- **Tag fields** page no longer gets huge and slow from Traktor data: private ID3 fields (e.g. `PRIV:TRAKTOR4`, where Traktor stores its waveform, beat grid and cue points) are listed once by their program instead of once per file with all their data in the name. The next scan re-reads every file once to apply this.
- Times (e.g. on History) show in your local time again after a page updates in place; since 0.8.2 they sometimes showed as raw UTC like `2026-10-05T21:18:06`.

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

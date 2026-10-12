# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.24.2] - 2026-10-12

### Changed
- **The Inbox is much faster with many tracks.** With a few hundred tracks, the Inbox took about 3 seconds to open, a track's review page about 3.5 seconds and Home almost 2 seconds. Tagwerk now reads what it knows about all inbox tracks at once instead of asking its database a dozen times per track; on a copy of a 330-track inbox, building the list went from about 1.2 seconds to 0.1 seconds. Nothing on the pages changes.
- The regular inbox check no longer goes through every track to see whether it needs an online lookup or an audio analysis: it picks the ones that do in one go, so opening the Inbox isn't slowed down by the check it starts.
- After an inbox check that found nothing new, the Inbox no longer reloads itself: **Check again** comes back with a short "Nothing new".

### Fixed
- When an import (or an inbox check) finished while the Inbox was loading, the page could keep showing the old list, e.g. *All 330* after importing 3 of 330 tracks, and no "Imported" message. The page now updates once the job is done.

## [0.24.1] - 2026-10-12

### Fixed
- **Copies are found when the artists are in another order or the title says "Original Mix".** *Crystal Clear & Creatures – Backin* in the inbox wasn't recognised as *Creatures, Crystal Clear – Backin (Original Mix)* in the library, so its FLAC wasn't offered as a better copy. Artists now match when they share a name, in any order.
- **The length decides between versions.** Words that only name a version (*Original Mix*, *Extended Mix*, *Radio Edit*, *Club Mix*, …) no longer make two files different tracks: stores use them loosely, so the same length (within 3 seconds) means the same track and a much shorter radio edit stays a different one. A remixer's name (*Jus Ron Edit*, *Hush Remix*) still means another track. When a length is unknown, only the very same title counts. This applies to the inbox's *In library* / *Better sound* and to the Duplicates page.

## [0.24.0] - 2026-10-12

### Added
- **Better copies replace the library copy.** When a new file in the inbox sounds clearly better than the same track in your library (lossless instead of MP3, 320 instead of 192 kbps, 24 instead of 16 bit), the Inbox marks it **Better sound** (badge and tab). Its page compares both copies and has **Replace library copy**:
  - the new file gets your library copy's tags and cover; fields the library copy doesn't have keep the new file's values;
  - it takes the old file's folder and name, with its own extension (`Artist - Title.mp3` → `Artist - Title.flac`);
  - the track stays the same track: added date, history and final mark stay;
  - the old file goes to the library trash (Duplicates page) until you empty it, and the History can undo the whole replacement.

  Tick several on the **Better sound** tab to replace them at once. The same track counts as better only when the sound is clearly better: a 300 kbps VBR file doesn't replace a 320 kbps one, and an MP3 never replaces a lossless file.
- **Replace automatically**, a new switch in Settings → Import (off by default): the regular inbox check replaces library copies with better ones on its own, for files that are fully downloaded and clearly the same track. A notification topic *Better copies replaced* (off by default) tells you which.
- Statistics → Tagwerk's work counts **Better copies**, with the list of tracks.
- The API has `POST /api/inbox/upgrade`; `GET /api/inbox` tells each track's `better_copy`.

### Fixed
- The Duplicates page ranked AAC files (`.m4a`) as lossless, above a 320 kbps MP3, and compared MP3s by sample rate before bitrate. Lossy copies are now compared by bitrate, and only FLAC, WAV and AIFF count as lossless (as in Statistics).
- The inbox's duplicate box shows the full quality of both copies (sample rate and bit depth for lossless files).

## [0.23.1] - 2026-10-12

### Fixed
- The artist name on a track page now leads to that artist's tracks. It used to go by the album artist, so after an online lookup corrected *CRYSTAL CLEAR* to *Crystal Clear*, the link still opened the old *CRYSTAL CLEAR* (the album artist hadn't changed). The track list has a new `artist` filter for this; the album link still goes by album artist.

## [0.23.0] - 2026-10-12

### Added
- **Fix a track's ReplayGain on its own page.** The **From the audio** box now has a **Loudness** line below BPM and key. When the ReplayGain doesn't fit the audio, it says what's wrong and what the tag should be, with one button, like the BPM and key suggestions:
  - an old ReplayGain 1 value or a gain that doesn't match: **Use −10.80 dB**
  - no ReplayGain at all: **Add ReplayGain**
  - the gain is right but the peak is missing: **Add the peak**

  The button creates a pending change (track gain and peak; Opus only has the gain), so you review and apply it on the Changes page as usual, with undo. Once it's waiting there, the box says so instead of showing the button. Final tracks show their loudness without a suggestion. The **ReplayGain** page stays the place to fix many tracks at once.
- Tracks that have BPM and key but no loudness yet (for example ones imported from the inbox) get a **Measure loudness** button in the box: it measures only the loudness, in about 2 seconds, and the box updates by itself. **Analyse** still measures BPM, key and loudness together.
- The *Doesn't match the audio* link in the **File** card now jumps to the box on the same page instead of the ReplayGain page.
- The API has `POST /api/tracks/{id}/replaygain/fix` and `POST /api/tracks/{id}/loudness`.

### Fixed
- The **ReplayGain** page kept listing a track after its fix was waiting on the Changes page when the file already had the right peak (only the gain needed a change).
- Buttons in the **From the audio** box (Analyse, **Use 175**, …) no longer send you to the top of the track page: the box stays where it was.
- On phones, a long status in the track page's **File** card (*Old ReplayGain 1 value (about 4 dB too loud)*) wraps instead of making the page scroll sideways.

## [0.22.1] - 2026-10-12

### Added
- **Tick many tracks at once on the Tracks page**: tick one track, hold **Shift** and click another, and every track in between is ticked too. A Shift-click that unticks a track unticks the ones in between, so you can trim a selection the same way. The box in the header shows when every track on the page is ticked.

### Fixed
- **"Longer version" finds the long version whatever a store calls it.** Stores name versions loosely: the long one is the *Original Mix* on Beatport but the *Extended Mix* elsewhere, and a *Radio Mix* is usually the same as a *Radio Edit*. Tagwerk only knew some of these words, so a file tagged "(Radio Mix)" that is really the 6:30 Original Mix didn't count Beatport's Original Mix of the same length, and the card said Beatport only had the short version. Now *original, extended, radio, club, single, album, short, mix, edit* and *version* at the end of a title all mean "a version of the same track", and the length decides which one your file is. Remixes and other people's edits ("Hush Remix", "Dimitri Edit") still count as other tracks.

## [0.22.0] - 2026-10-11

### Added
- **Secret tracks, for your edits and bootlegs.** An edit shares the original's artist, title and much of its sound, so online sources find the original release and suggest its label, cover and IDs. And bootlegs rarely have official artwork. A track marked **Secret**:
  - is **never looked up online**: no source is asked, not even AcoustID with the audio. Whatever was found online before is forgotten when you mark it.
  - is **complete without a cover**: set-ready, ready for **Mark as final**, and imported automatically (in automatic mode) without one. *Missing cover art* and the inbox's "Needs cover" leave secret tracks out.
- **How to mark tracks:**
  - Put edits and bootlegs into a folder called **`Secret`** inside your import folder (subfolders count). Tagwerk marks them as soon as it finds them, before any lookup. The folder doesn't change where a track goes in your library, and the filename stays the same.
  - Use the **Secret** switch at the top of a track's page or its inbox page.
  - Tick tracks and press **Mark as secret**, in the track list or in the inbox's bottom bar. The track list's new *Secret* filter and the inbox's *Secret* tab list them, and there the button removes the mark again.
  - The mark is kept in Tagwerk only, like *Final*; nothing is written into the files. It moves with a track when it's imported, and back if you undo the import.
- The **Inbox** explains the `Secret` folder in a message you can hide for good with **Don't show again** (on every device; the same message on the track list's *Secret* filter goes with it). Settings → Online lookups keeps a short note.
- Secret tracks show a violet **Secret** label in the track list, the inbox and on Final check. Their *Online sources* card says they're not asked, and Statistics counts them under *Missing tags*. Everything that runs on your server works for them as before: BPM and key from the audio, loudness and ReplayGain, Fix IDs, mix names, duplicates, Convert to AIFF.
- The API has `POST /api/tracks/secret` and `POST /api/inbox/secret`, and tracks carry `"secret": true/false`. Hidden messages are in the settings as `hidden_hints`.

### Changed
- **Look up online** for several tracks leaves secret tracks out and says how many. When you take the mark off an inbox track, Tagwerk looks it up straight away, like any new inbox track.

## [0.21.2] - 2026-10-11

### Fixed
- **New drum & bass tracks get 174 BPM, not 87.** When a new track was analysed and looked up online at the same time, the BPM was decided without the genre found online, because that genre was still only a pending change. Stores often list drum & bass at 87, so Changes could show "Drum & Bass" next to 87 BPM. The pending genre now counts like a genre tag, and a BPM Tagwerk proposed earlier from the audio is corrected (or dropped if it's no longer sure). BPMs you entered yourself are never replaced. Tracks that already show 87 get fixed the next time they're analysed or looked up again.

## [0.21.1] - 2026-10-11

### Added
- **Settings → General → Time zone** (the section was called Display): dates in notifications, like "removed for good on 14 Oct", use your time zone. Settings offers your browser's with one click; left empty, the container's is used (Unraid sets it for every container).

### Changed
- **The bell shows 9+** from 10 unread notifications on, so the number never covers the bell in the side menu. Screen readers still hear the whole number.

### Fixed
- **Home keeps up while it stays open**: "Waiting for you" (the notifications that need you, the inbox numbers, pending changes) now updates every minute like the bell's number, not only when you change pages.
- **A wrong AcoustID key is reported at once**, like a wrong Discogs token. AcoustID says "invalid API key" with an error 400 instead of 401/403, so until now it only showed up after 5 failed lookups as "AcoustID keeps failing".

## [0.21.0] - 2026-10-11

### Added
- **Notifications: what Tagwerk did while you were away.** A bell with the number of unread notifications sits next to the logo in the side menu (on phones: in the top bar, between Changes and the menu). It opens a short list of what happened; a click shows the details with a link to where you can act, and **✓ Read** moves it to the History. Nothing is marked as read or removed by itself: **Mark all as read** and **Clear history** are on the notifications page (**All** at the bottom of the bell's menu). Home's "Waiting for you" shows a line when something needs you.
  - You choose what is reported in **Settings → Notifications**. Switched on from the start, only what needs you or could lose data: files in the **inbox trash** 3 days before they are removed for good (with a link to restore them), **more inbox tracks needing your help**, a **scan skipped** because the music folder looked empty or **files that couldn't be read**, **Navidrome not answering**, and an **online source rejecting its key** or failing again and again.
  - Switched off until you want them: **tracks imported automatically** (with a link to the History) and **long jobs finished** (audio analysis or online lookups you started for many tracks).
  - Kept short: one notification per job, never one per track; a problem that lasts is reported once, and once more when it is fine again.
- On phones narrower than 430 px the top bar shows the logo without the word "Tagwerk", so the bell fits.

### Fixed
- **Home**: in the "Waiting for you" card, "Nothing waiting." no longer sits right on top of the "Last analysis" box below it.

## [0.20.0] - 2026-10-11

### Added
- **Discogs track IDs**: taggers write a Discogs track as the release number and the track's position, like `33199809-3` (track 3 of release 33199809). Tagwerk now keeps them in their own field, **Discogs track ID** (`DISCOGS_TRACK_ID`), shown on the track page next to the release and artist IDs and linked to the release's page.
  - **Fix IDs** and the import move a Discogs track from the MusicBrainz track ID field into **Discogs track ID** (and its release number into **Discogs release ID**). Until now only the release number was kept and the position was lost. A Discogs track ID already in the file stays.
  - The **online lookup** finds the track in the Discogs release's tracklist (same title, and the same length when Discogs knows it) and suggests its track ID together with a sure Discogs release.
  - Tagwerk reads every file once more on the next scan, to pick up Discogs track IDs that are already there.
  - Tracks fixed with an earlier version lost the position in their files: undo that **Fix IDs** on the History page and run it again, or look the track up online.
- **Beatport as an online source**: the DJ store sells the club versions that streaming stores often don't have, each with its own length, mix name, BPM, key, genre and label. Tagwerk reads Beatport's public search page (Beatport has no API for individuals), one request per lookup, no account needed. New installs have it switched on; on an existing install, switch it on in **Settings → Online lookups**.
- **Longer versions are recognised**: when your file is longer than the only version some sources have, the Online sources card says so and names the sources that list your file's length. For example, Billy Kenny's "Take Me To Church" (5:26): "MusicBrainz, Deezer and iTunes only have a 4:09 version. Discogs and Beatport list this 5:26 version (Original Mix)." Values such as label and genre then come from the matching version.
- **Beatport's key helps the audio analysis**: when Beatport's key matches what the audio hears, the key is sure; when it doesn't, the track page says so.

### Changed
- **Discogs knows each version**: Tagwerk now reads the tracklist of the best Discogs releases, so a release with an Original Mix (4:08) and an Extended Mix (6:41) gives two results with their own lengths, and the right one is picked. Discogs' numbers after artist names ("Fisher (16)") are dropped.
- **"Original Mix" counts as the plain title**: "Big Up (Original)" and "Big Up" are the same title when results are compared.
- **The audio decides the BPM**: for a library track whose audio was analysed, online lookups no longer stage a BPM on their own. Two stores agreeing on 87 doesn't make a drum & bass track 87 BPM; their values still help the analysis choose.

## [0.19.4] - 2026-10-11

### Added
- **MusicBrainz and Discogs IDs from the online lookup**: the sources already sent the IDs of the tracks they found; Tagwerk now keeps them and suggests them, more carefully than other values, because a wrong ID is worse than none (Navidrome and Picard trust it):
  - **The MusicBrainz recording** (and its artists) only when AcoustID recognised the sound clearly, or when AcoustID and MusicBrainz name the same recording. Two sources agreeing on the title isn't enough.
  - **The MusicBrainz album IDs** only from the track's own release on MusicBrainz, when it is the track's album; never from a compilation.
  - **The Discogs release and artist IDs** when MusicBrainz links to that Discogs release, or when the Discogs release is the track's album and its label or catalog number agrees. With several pressings (vinyl, digital, reissue) the one matching label and catalog number wins, otherwise none.
  - **Only empty ID fields** are filled; IDs your files already have are never replaced. While a MusicBrainz field holds a Discogs number, run **Fix IDs** first.
  - **Library tracks**: sure IDs become pending changes after *Look up online*, like the other sure values (final tracks get nothing). **Inbox tracks**: they are written on import, and the review page lists them. **Use these values** takes a result's IDs over too.
  - Each ID is a **link** to its page at MusicBrainz or Discogs, on the Online sources card, the Changes page and the inbox review page, so you can check where it points before you apply.
  - Tracks looked up before this version get their IDs with **Look up again** (or, for many at once: Tracks → *Missing: MusicBrainz IDs* → *Look up all matching tracks*).

### Changed
- **Each source on the Online sources card folds on its own**: click a source's name to close or open its panel. Sources that found the track (or couldn't be asked) start open, the others closed, so the card stays short.

## [0.19.3] - 2026-10-11

### Fixed
- **Genres from online lookups are matched against your genre map**: iTunes sends store categories such as "Jungle/Drum'n'bass", which arrived as pending changes as they were. Tagwerk now checks each part against the genre map, and when all parts belong to the same main genre, the suggestion is that genre: "Drum & Bass". The Online sources card, "Use these values" and the values staged after "Look up online" all show the matched genre. Categories that mix two main genres ("House/Techno") or name one the map doesn't know stay as the source sent them; add a line to the genre map in Settings to match them too.

## [0.19.2] - 2026-10-11

### Changed
- **The title in the play bar opens the track's page**: click it to get to the playing track (or its Inbox page) from anywhere.

## [0.19.1] - 2026-10-10

### Changed
- **A Tools section in the menu** with **ReplayGain**, **Convert**, **Mix names** and **Genre spellings**. ReplayGain, Mix names and Genre spellings were only linked when there was something to fix, so the ReplayGain page couldn't be found before the first measurement. Duplicates stays under Work.
- **Home points to unmeasured tracks**: "Worth a look" shows how many tracks don't have their loudness measured yet, with a link to the ReplayGain page.

### Fixed
- **The analysis progress on Home ran out of its box**: in the narrow "Waiting for you" card, the line "Analysing the audio …: 671 of 1,355 tracks" didn't wrap, and the sentence under it was broken into separate pieces. It now wraps as one paragraph, with Stop below it.

## [0.19.0] - 2026-10-10

### Added
- **Release notes on GitHub**: every new version now gets its own page under [Releases](https://github.com/dooziedan/tagwerk/releases), with that version's changes from this changelog and the image to pull. Choose *Watch → Custom → Releases* on GitHub to get notified about new versions.
- **ReplayGain checked against the audio**: a new **ReplayGain** page (linked from "Worth a look" on Home) measures how loud every track really is (EBU R128, with ffmpeg, about 2 seconds per track in the background) and compares it with the track's ReplayGain tag. It lists the tracks to fix: no ReplayGain, a gain that doesn't match the audio, an **old ReplayGain 1 value** (older taggers used a reference about 4 dB louder, so those tracks play louder than the rest), or a missing peak. Tick them and Tagwerk creates pending changes with the measured track gain and peak (ReplayGain 2.0, -18 LUFS), so Navidrome plays every track at the same level. Nothing is written until you apply; final tracks are skipped, and undo works as usual.
- **Loudness on the track page**: the measured loudness (LUFS) and the ReplayGain it should have, with a note when the tag doesn't match. The page also shows how loud your library typically is.
- **Analysing a library track also measures its loudness** (track page, ticked tracks, or all tracks of the list). Tracks whose BPM and key were analysed before only get the quick loudness pass.

### Changed
- **Changes page on phones**: held upright, a phone squeezed each change into narrow columns, so old and new values were only a few letters wide. Each change is now a small block: the tick box, the field and **Discard** on top, the old value below, and the new value under it. Proposed genre folders show the old and the new path the same way, and so does a change's detail page in the history. Turned sideways, on a tablet or a computer, the page keeps old and new side by side.
- **History on phones**: the list ran off the right edge of the screen, hiding the status and the **Undo** button. On a phone held upright, each Apply is now a small block: when it happened (tap for the details) and **Undo** on top, the fields below, then "2 files · applied".
- **A new "Online sources" card** on the track page and the inbox review page (it was "Found online"). It is folded by default, so the page stays calm: the closed card shows one pill per source with its best match (green: found, orange: no good match, red: couldn't ask). Click it to open; it remembers whether you left it open. Inside, every source has its own panel, with plenty of space around it, a coloured edge, its score and a few words on what it is good for (AcoustID recognises the sound itself, Discogs knows labels and catalog numbers, …). The best match comes first with its values side by side, each marked **✓** (same as your tags), **new** (fills an empty field) or **yours: …** (your file says something else), so you see what **Use these values** would change before you press it. Weaker results are folded away below. **Look up again** stays in the top corner, also when the card is closed.
- **On the inbox review page** the card always starts closed and shows an orange **Check 2 matches** tag while sources found the track, so you don't forget to look before importing. The tag goes away when you open the card.

## [0.18.3] - 2026-10-10

### Changed
- **Discogs IDs in MusicBrainz fields are fixed on import.** Some taggers write Discogs numbers into the MusicBrainz ID fields. Until now Tagwerk only fixed them in the library (**Fix IDs**), so every import brought them in again. Now the import does the same fix: real MusicBrainz IDs stay, Discogs numbers and links move to **Discogs release ID** / **Discogs artist ID**, anything else is removed. The inbox review page lists each value and what happens to it. Undoing the import puts the old values back.

### Fixed
- **Discogs IDs like `33199809-10`** (release 33199809, track 10), as some taggers write the MusicBrainz track ID, were treated as unknown and would have been removed. They are now recognised: the release number moves to **Discogs release ID**, on import and with **Fix IDs**.
- **The ID panel on the track page was cut off** at the bottom (the **ⓘ** button): with many IDs, the artist rows were hidden behind the header's edge. It now shows in full, on a solid background, and fits on a phone screen.

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

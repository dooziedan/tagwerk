# Roadmap

## Goal
Tagwerk manages the Unraid/Navidrome library, which is the owner's master library. New music
arrives in a separate **import inbox**; Tagwerk tags it as far as it can on its own, asks the
owner only where it's unsure, then moves finished tracks into the library. Rekordbox and the DJ
SSD are out of scope (that would be a separate tool).

**1.0 means:** Tagwerk can be trusted with the real master library, and it is a joy to look at.

## Where we are (v0.15)
Everything on the original plan is built: scanning and statistics, editing with review and undo,
the import inbox with automatic mode, online identification, BPM and key from the audio, final
tracks, converting to AIFF, the play bar, the night-sky look, duplicates in the library (with
the copy to keep and a trash) and the README. What's left before 1.0: the owner's run on the real library
and an onboarding tour.

## Road to 1.0
In this order:

1. **Tagwerk's work** ✅ v0.11: what Tagwerk did for the library, and where each value came
   from ([ADR 0020](decisions/0020-tagwerks-work.md)).
2. **Apply ticked changes** ✅ v0.11: tick the pending changes to apply or discard; unticked
   ones stay pending.
3. **Visual rebrand** ✅ v0.12, polished in v0.13: the night-sky look
   ([ADR 0021](decisions/0021-night-sky-rebrand.md)). v0.13: orbits drawn in 2D with round
   moons, short card entrances instead of the page-change warp, big effects only for Convert
   (hyperspace jump) and Apply (golden burst), notifications that slide in, a tidier Settings
   page.
4. **Duplicates in the library** ✅ v0.13: groups of copies side by side, a number on Home and
   Statistics, "keep them all"
   ([ADR 0022](decisions/0022-library-duplicates.md)). v0.14: suggests the copy to keep (the
   best sound) and lets the owner take tags and covers over from the other copies; v0.15: the
   other copies can go to a library trash that only the owner empties
   ([ADR 0023](decisions/0023-library-trash.md)).
5. **Hardening on the real library**, partly done:
   - ✅ Speed at full size: `scripts/benchmark.py` times every page on a made-up library of
     20,000 tracks. A missing index made Home take 3.5 s and Statistics 10.7 s; now 0.15 s and
     0.85 s, every other page under 0.6 s.
   - ✅ A test upgrades an old database through every migration with data in every table, reads
     it with today's code and downgrades it again.
   - ✅ After every scan or write, BPM/key decisions are worked out again: 7 s → 2 s at 20,000
     tracks (online results are only read for tracks that were looked up).
   - ✅ The Unraid template has every setting (a test keeps it that way), with a **CPU Cores**
     field in the main view.
   - ✅ v0.14: a scan never empties the library when the music folder looks empty (unmounted
     share); files moved outside Tagwerk keep their added date, final mark and analysis.
   - In progress: **the owner's real library** on Unraid (about 1,500 tracks, filled through
     the import inbox from a separate DJ library): scan time, memory and page times; WAV/AIFF
     tags compared with what Navidrome shows (open since v0.2).
6. **Polish** ✅ v0.14: glass for the edit form and the wizard, a planet on the track page
   when there is no cover, the Play button matches the buttons next to it, unused old rules
   retired.
7. **README** ✅ v0.14: screenshots from a made-up showcase library and a "first steps" guide.
8. **Onboarding tour**: after the setup wizard, a short guided look at the interface for people
   new to Tagwerk. It highlights one area at a time with a sentence or two and *Next* / *Skip*:
   the menu (Library, Work, System), Home's "Waiting for you" and "Worth a look", the way every
   edit becomes a pending change (Changes → Apply → History and undo), the Inbox, Duplicates,
   Statistics, and where Settings live. On the owner's real library, not a demo; works on
   phones; shown once, and again from Settings (*Show the tour*). Calm, like the rest of the
   motion: no constant movement, nothing with reduced motion.
9. **Release `v1.0.0`** once the owner's real-library run (5.) shows nothing more to fix.

## Planned features
Noted by the owner (2026-10-08); not yet placed before or after 1.0.

- **ReplayGain: analysis and editing**
  ([issue #39](https://github.com/dooziedan/tagwerk/issues/39)). Tagwerk reads the track gain today but can't measure or change it. Measure loudness from the audio inside
  the container (EBU R128 / ReplayGain 2.0: track gain and peak, album gain and peak for real
  albums; ffmpeg is already in the image), offer the results as pending changes like BPM and
  key, and make the ReplayGain fields editable in all 7 formats, including Opus's own
  `R128_TRACK_GAIN` and exact undo. Navidrome uses these tags to even out playback volume.
  *Done: all four fields are read and editable in every format ([ADR 0028](decisions/0028-replaygain.md)); loudness is measured and the tags checked and fixed on the ReplayGain page ([ADR 0029](decisions/0029-loudness-and-replaygain-check.md)).*
- **Even loudness on the decks: change the sound itself**. CDJs and XDJs don't read ReplayGain. Apply the measured gain to the audio of lossless files (AIFF, WAV, FLAC: exact, no timing shift, so rekordbox cues stay right), keeping originals and undo like Convert. Lossy files would need re-encoding (quality loss, possible timing shift) and stay out. A separate release, decided by the owner (2026-10-09).
- **Advanced tags on the edit page**
  ([issue #40](https://github.com/dooziedan/tagwerk/issues/40)). A switch on a track's edit page that shows every tag field
  in the file (the raw fields the track page lists, with what each one feeds) and lets the owner
  change, add or remove them, through pending changes with review, apply and undo like every
  other edit. Binary fields (pictures, private data) can be removed but not typed into; a field
  that feeds a Tagwerk field (e.g. `TBPM` → BPM) says so, so the two never fight. Needs a raw
  field path in the writer for every format, with snapshots for exact undo
  ([ADR 0009](decisions/0009-writing-tags.md)).

## Released
Details are in the [changelog](../CHANGELOG.md) and the [decisions](decisions/README.md).

| Version | What came | Decisions |
|---|---|---|
| 0.1 | Docker image with PUID/PGID, Unraid template, CI. Verified on Unraid 7.3.2. | [0001](decisions/0001-tech-stack.md), [0002](decisions/0002-unraid-deployment.md) |
| 0.2 | Library scan (background job, unchanged files skipped), database with migrations, dashboard. Numbers checked against `ffprobe`. | [0005](decisions/0005-reading-tags.md) |
| 0.3 | OGG and Opus; BPM, key (any notation), comment, label, catalog number, ReplayGain, lyrics; DJ and Collector modes. | [0006](decisions/0006-modes.md) |
| 0.4 | Tag fields page: every raw field of every file. Found why few tracks had a BPM (Picard writes `0`). | |
| 0.5 | Browse and search: track list with filters, artists, albums, track page; every dashboard number opens its tracks. 0.5.1: design language and cross-browser screenshots. | [0008](decisions/0008-design-language.md) |
| 0.6 | The writing engine: edit one or many tracks → pending changes → review → apply → undo, all 7 formats; covers in 0.6.1. | [0003](decisions/0003-review-before-write.md), [0009](decisions/0009-writing-tags.md) |
| 0.7 | Import inbox (suggestions, review, import by folder layout with the filename unchanged, Navidrome rescan), setup wizard, new genre folders after review, inbox duplicates and trash, final tracks with optional renaming, convert to AIFF. | [0007](decisions/0007-import-inbox.md), [0010](decisions/0010-new-genre-folders.md), [0011](decisions/0011-inbox-duplicates-and-trash.md), [0012](decisions/0012-final-tracks.md), [0013](decisions/0013-convert-to-aiff.md) |
| 0.8 | Online identification (MusicBrainz, AcoustID, Discogs, Deezer, iTunes), also for library tracks; the play bar; private ID3 data named and removable. | [0014](decisions/0014-online-identification.md), [0015](decisions/0015-player.md), [0016](decisions/0016-private-data-cleanup.md) |
| 0.9 | BPM and key from the audio (Essentia), tuned for bass-heavy music; Fix IDs for MusicBrainz fields holding Discogs numbers. | [0017](decisions/0017-audio-analysis.md), [0018](decisions/0018-musicbrainz-and-discogs-ids.md) |
| 0.10 | Home and Statistics instead of one dashboard, parallel audio analysis, History pages. | [0019](decisions/0019-home-and-statistics.md) |
| 0.11 | Tagwerk's work, value sources, ticking changes to apply. | [0020](decisions/0020-tagwerks-work.md) |
| 0.12 | The night-sky look. | [0021](decisions/0021-night-sky-rebrand.md) |
| 0.13 | Duplicates in the library, speed at full size, tidier Settings, 2D orbits, new motion. | [0022](decisions/0022-library-duplicates.md) |
| 0.14 | The copy to keep among duplicates, safer scans, honest percentages, the stardust Apply, README screenshots. | [0022](decisions/0022-library-duplicates.md) |
| 0.15 | A trash for duplicate copies (emptied only by the owner), Apply in a sensible order, long lists. | [0023](decisions/0023-library-trash.md) |

## Later / ideas
Not planned for 1.0; open for discussion.
- **Navidrome numbers** on Home: play counts and most played from Navidrome. (Most played *as a
  DJ* would need Rekordbox data, which is out of scope.)
- **Online keys**: an extra source with tempo and key (e.g. GetSongBPM, if its terms allow) to
  confirm the audio analysis; Deezer only has BPM.
- **Remove all private data** in one action, and a finder for PRIV data Tagwerk can't see (a
  second ID3 tag, a tag at the end of an MP3, ID3 in front of a FLAC).
- **Energy or danceability** from the audio (Essentia) for statistics and set prep.
- **Daily library snapshot** for trend lines in Tagwerk's work (set-ready, missing BPM/key/genre/
  cover over time), one row per day ([ADR 0020](decisions/0020-tagwerks-work.md)).
- **Set prep**: harmonic mixing helpers (compatible keys), BPM/key filters.
- **Batch jobs** for the existing library (e.g. look up everything without IDs).
- **Reorganising the existing library** by the folder layout (so far only new inbox tracks are
  sorted; check how Navidrome handles moved files first).
- **Filename parsing**: scene-style names (`artist-title-(vip)-128bpm`) and BPM/key at the end
  without brackets (`… (Extended Mix) 174 Am`) aren't read yet; `[174 Am]` is.
- Last.fm genres.
- Login protection (low priority: Tagwerk is a local tool for one user).

# 0036: Secret tracks: edits and bootlegs, never looked up online, complete without a cover
Date: 2026-10-11 · Status: Accepted

## Context
Tagwerk is for DJs with official **and** unofficial tracks ([ADR 0024](0024-made-for-djs.md)). Many of the owner's tracks are edits, bootlegs and mashups. Two rules made for official releases get in their way:

- **Online lookups find the original.** An edit shares the original's artist, title and much of its sound. The scoring treats "Rio" and "Rio (Someone Bootleg)" as possibly the same track in another version, and AcoustID may recognise an edit's audio as the original clearly enough to count as sure on its own. So the original release's label, catalog number, year, cover and MusicBrainz IDs get suggested, in the library as pending changes and in the inbox, with automatic import, written without asking. Privacy is a minor point (a lookup is a search, nothing is published, and AcoustID only stores fingerprints that are submitted, which Tagwerk never does), but promos under NDA are better not searched for either.
- **Bootlegs rarely have official artwork,** so they could never be set-ready or marked final (both asked for a cover, [ADR 0012](0012-final-tracks.md)).

The roadmap's planned release watch already named the remedy: a per-track "Don't check online" switch for bootlegs, private edits and promos.

Inbox tracks are looked up as soon as the inbox check finds them, before the owner can look at them. A switch alone would come too late for the first lookup.

## Decision
**A secret mark**, kept only in Tagwerk's database (`secrettrack` for library tracks, `secretinboxtrack` for inbox tracks), never as a tag, like the final mark. A secret track:

1. **is never looked up online.** No source is asked, not even AcoustID with the audio: not by the inbox check, *Look up again*, *Look up online* (one track or many), *Look up all N* or the API. A batch lookup says how many secret tracks it left out. What online sources found before is **forgotten** when a track is marked (its suggestions, cover suggestion and IDs go with it), and the audio's BPM and key decision is worked out again without those online hints. A track marked while its lookup runs keeps none of the answers: the lookup checks the mark after every source and stops.
2. **is complete without a cover.** One rule everywhere: set-ready (`app/library.py`, so Home, Statistics, the track list, Tagwerk's work), Final check and *Mark as final*, automatic import, and the inbox's "Needs …". *Missing cover art* leaves secret tracks out, since they don't need one; Statistics says how many secret tracks there are.

**Marking.**
- **The import folder's `Secret` folder** (any capitals, subfolders count): files there are marked when the inbox check first finds them, before the lookup that follows it. The folder doesn't decide where a track goes in the library, and the filename stays the same. The folder only marks new files: a track the owner unmarks stays unmarked.
- **A Secret switch** at the top of the track page (also on final tracks) and of the inbox review page. Switching sends at once.
- **Ticked tracks**: *Mark as secret* in the track list and in the inbox's bottom bar. The track list's *Secret* filter and the inbox's *Secret* tab (shown only when there are any) list them, and there the button becomes *Not secret*.
- **API**: `POST /api/tracks/secret` and `POST /api/inbox/secret` (`track_ids`, `secret`), and `secret` in the track and inbox JSON.

**Removing the mark.** An inbox track is looked up at once, like any new inbox track. A library track is looked up only when the owner asks, as before. A final track keeps its final mark; without a cover it then counts as not set-ready, which Home shows.

**The mark moves with the track**: into the library on import, back into the inbox when the import is undone (the inbox row is created right away, so the next inbox check doesn't take the file for a new one and look it up). Files moved outside Tagwerk keep their row and the mark; so do Convert to AIFF and its undo.

**Shown** as a violet **Secret** pill (`--tw-secret`, the decades chart's violet, 6.5:1, always with the word): track list rows, inbox rows, Final check. The *Online sources* card of a secret track is one line: "Not asked: the track is secret." Toasts confirm each change. The Inbox (and the track list's *Secret* filter) explains the folder in a message the owner can hide for good with **Don't show again**: stored in the preferences (`hidden_hints`), so it stays hidden on every device, and one press hides it in both places. Settings → Online lookups keeps a short note for later.

**Everything that runs on the server treats secret tracks like any other:** BPM and key from the audio, loudness and ReplayGain, Fix IDs, mix names, genre spellings, duplicates, Convert to AIFF and notifications.

## Consequences
- Tagwerk can't help a secret track with online values. Its suggestions come from the file, the filename and the audio; the owner fills the rest.
- Switching the mark isn't recorded in the History: it writes nothing and is undone by switching back (the forgotten online results come back with a new lookup).
- A file deleted from the inbox and restored from its trash is read as new: in the `Secret` folder it is secret again, elsewhere it loses a mark set by hand.
- The planned release watch and AcoustID sharing ([roadmap](../roadmap.md)) leave secret tracks out: they aren't releases.

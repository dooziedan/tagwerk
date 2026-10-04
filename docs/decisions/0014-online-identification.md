# 0014: Online identification of inbox tracks
Date: 2026-10-04 · Status: Accepted

## Context
Inbox tracks often arrive with few tags. Filenames give artist and title; online databases know release dates, labels, catalog numbers, genres and cover art. The owner chose four kinds of sources: MusicBrainz, AcoustID (fingerprints), Discogs, and the iTunes/Deezer store catalogues. Results go to the inbox first; library tracks come later.

## Decision
- **One interface** (`app/sources/base.py`): a source gets a `Query` (artist, title, length, file) and returns `Candidate`s with values for Tagwerk's editable fields, a link and maybe a cover URL. Sources are thin translations of one API each; scoring and combining live in `app/identify.py`.
- **Standard library HTTP**, a User-Agent naming Tagwerk, a timeout, and a minimum gap per source (MusicBrainz 1/s, Discogs 60/min, iTunes ~20/min, Deezer 50/5 s, AcoustID 3/s). No new Python dependency. AcoustID's `fpcalc` (Chromaprint) is in the image; it reuses ffmpeg's libraries.
- **Keys are the owner's**: `ACOUSTID_KEY` (free application key) and `DISCOGS_TOKEN` (free personal token) as container variables. Without them those sources are skipped. Each source can be switched off in Settings.
- **Only artist, title and the fingerprint** leave the server; never the file.
- **Results are stored** (`onlinelookup`), asked in a background job after each inbox check that doesn't take the library lock (network and database only). A source is asked again when the owner changed artist or title, after 30 days, after an error, or on *Look up again*.
- **Scoring**: title with the mix name (an Extended Mix is not the Radio Edit), main artist, and length (±3 s full, ±10 s reduced, more: a different edit). AcoustID's audio score counts most. Candidates below 75 % aren't used.
- **Suggestions only fill empty fields**; tags in the file and the filename suggestions come first. A value is **sure** when two sources agree on it (dates by year, text ignoring case and spelling), or when AcoustID recognised the audio clearly (title, artist, album); otherwise "check". The owner's Automation setting decides what may be imported without asking, as before.
- **Cover art**: for a track without a cover, the best match's cover is downloaded once (https, ≤10 MB, JPEG/PNG checked) and suggested; sure under the same rule.
- The review page lists every source's answer with its match, a link to the source's page and **Use these values** (all values and the cover of that result become the owner's values).
- MusicBrainz albums from compilations aren't suggested ("The Annual 2019" isn't a club track's album).

### Library tracks (added in 0.8.1)
- **Look up online** for library tracks: on a track page, for ticked tracks, or for all tracks matching the list's filters. Same sources, scoring and stored results (`librarylookup`).
- Because library files only change through review → apply (ADR 0003), **sure values for empty fields become pending changes** by themselves (the cover too); the owner reviews and applies them on the Changes page. Fields the owner already edited (pending) are left alone; **final tracks** get nothing staged (they are locked), but their results can still be looked at.
- Everything that isn't sure waits on the track page, where **Use these values** stages one result.
- Every result says why it scored as it did ("same title and artist, but 3:49 long (this file: 0:01)").

## Consequences
- Edits, bootlegs and promos often aren't found; the filename suggestions and the owner stay in charge.
- Store genres are broad ("Dance"); Discogs styles are more useful. Genres are mapped through the genre map but are only sure when two sources agree.
- Tests never use the network: saved real answers feed the sources.

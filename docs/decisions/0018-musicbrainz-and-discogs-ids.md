# 0018: Fixing MusicBrainz ID fields, Discogs IDs in their own fields
Date: 2026-10-06 · Status: Accepted

## Context
Some taggers write Discogs numbers (or links) into the MusicBrainz ID fields. Since v0.3 the scan flags this (`mbid_invalid`, dashboard and track list), but the ID fields weren't editable, so there was no way to fix them. Navidrome and Picard expect real MusicBrainz IDs there; the Discogs numbers are still useful information.

## Decision
- The four MusicBrainz ID fields (track, album, artist, album artist) become writable for all 7 formats, with snapshot and exact undo like every field ([ADR 0009](0009-writing-tags.md)): ID3 `UFID:http://musicbrainz.org` and `TXXX:MusicBrainz … Id` (Picard's names), Vorbis `musicbrainz_*`, MP4 `----:com.apple.iTunes:MusicBrainz … Id`. They are not in the edit form; only **Fix IDs** changes them.
- Two new fields, read and written: **Discogs release ID** and **Discogs artist ID**, as `DISCOGS_RELEASE_ID` / `DISCOGS_ARTIST_ID` (the names Mp3tag uses; TXXX, Vorbis comment, MP4 freeform). `SCAN_VERSION` 5 reads them.
- **Fix IDs** (track page; or all flagged tracks from the track list) creates pending changes per track:
  - real MusicBrainz IDs stay (also when a field has several values and only some are wrong),
  - Discogs numbers, Discogs links (`discogs.com/release/123`) and Discogs markup (`[r123]`, `[a123]`) move to the Discogs fields: from the track and album fields to the release ID (Discogs has no track IDs), from the artist fields to the artist ID; existing Discogs values are kept,
  - anything else is removed.
- The track page shows each wrong value and what will happen to it, instead of only a warning inside the info pop-up.

## Consequences
- Inbox tracks are not fixed on import; they are flagged after import like any library track. (Changed in [ADR 0030](0030-ids-fixed-on-import.md): they are fixed on import.)
- Correct MusicBrainz IDs are not looked up here; that could come from the online lookup later.

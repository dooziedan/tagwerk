# 0005: One common tag format, Picard conventions, honest about bad data
Date: 2026-10-04 · Status: Accepted

## Context
The library mixes MP3, FLAC, WAV, AIFF and M4A. They use three tag systems (ID3, Vorbis comments, MP4 atoms), and some WAV files only have the older RIFF INFO chunk. Real files also contain surprises. One test file had Discogs IDs in its MusicBrainz fields, written by a tagger.

## Decision
- `app/tags.py` maps every format onto **one set of fields** (title, artist, album, album artist, track/disc number and total, date/year, genre, four MusicBrainz IDs, cover present). Everything above it (scanner, stats, UI) works on those fields only.
- Field names and storage follow **MusicBrainz Picard's conventions** (e.g. `TXXX:MusicBrainz Album Id`, `musicbrainz_albumid`, `----:com.apple.iTunes:MusicBrainz Album Id`), since that's what most taggers and Navidrome use.
- **WAV without ID3 falls back to RIFF INFO**, because Navidrome reads it too, and otherwise Tagwerk would disagree with Navidrome about those files.
- **Multiple values** (several artists or genres) are joined with `"; "`.
- **Values are stored as they are on disk, never "corrected" during a scan.** Problems are flagged instead: `mbid_invalid` marks MusicBrainz fields that don't hold a MusicBrainz ID, and `error` marks files that couldn't be read. One broken file never stops a scan.
- **Artists and albums are derived from tracks** (album artist, falling back to track artist, like Navidrome's artist list). There are no separate artist/album tables yet. They can be added when editing needs them (Phase 2+).

## Consequences
- Adding a format means one reader function in `tags.py` and a fixture in `tests/fixtures/`.
- The dashboard shows the library exactly as the files describe it, warts included. That's the point of the tool.
- Tag *writing* (Phase 2) must map the same fields back, and should write ID3 to WAV files (keeping their RIFF INFO untouched).

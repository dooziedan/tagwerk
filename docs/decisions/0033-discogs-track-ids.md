# 0033: Discogs track IDs
Date: 2026-10-11 · Status: Accepted · Changes part of [0030](0030-ids-fixed-on-import.md), extends [0032](0032-ids-from-the-online-lookup.md)

## Context
Taggers write a Discogs track as the release number and the track's position on it: `33199809-3` is track 3 of release 33199809 (Deadmau5 – Sofi Needs A Ladder on *4x4=12*). Discogs itself has no separate track IDs, but the owner's library has many of these, mostly in the MusicBrainz track ID field. [ADR 0030](0030-ids-fixed-on-import.md) moved them to **Discogs release ID** and dropped the position ("Discogs has no track IDs"), so which track of the release it was got lost. There is no common tag name for Discogs track IDs.

## Decision
- A new ID field, **Discogs track ID**, written as `DISCOGS_TRACK_ID` (ID3 `TXXX`, Vorbis comment, MP4 freeform), next to Tagwerk's `DISCOGS_RELEASE_ID` and `DISCOGS_ARTIST_ID` (Mp3tag's style). Read, written and undone in all 7 formats like the other ID fields ([ADR 0009](0009-writing-tags.md)); the scan reads every file once more (`SCAN_VERSION` 7).
- **The value** is the release number, a dash and the position as Discogs writes it: `33199809-3`, `4512-A1`. One value per track; the position keeps its spelling.
- **Fix IDs and the import** ([ADR 0030](0030-ids-fixed-on-import.md)): a Discogs track in the MusicBrainz *track* field moves to **Discogs track ID**, and its release number to **Discogs release ID**. A Discogs track ID already in the file stays. In the *album* field it is still read as the release.
- **The online lookup** ([ADR 0032](0032-ids-from-the-online-lookup.md)) finds the track in the release's tracklist, from the same Discogs request that brings the artist IDs: the only track with the file's title (another version's title only when the length agrees within 3 s; without a length, only the exact title). It is suggested only together with a sure Discogs release, for an empty field.
- A Discogs track ID links to its release's page (Discogs has no pages for single tracks).

## Consequences
- Other programs may not show `DISCOGS_TRACK_ID`: there is no standard name. The value stays readable for people (release and position).
- Tracks whose IDs were fixed before this version lost the position in their files. Undoing that **Fix IDs** in History and running it again keeps it now; otherwise the online lookup can find the track on Discogs again.

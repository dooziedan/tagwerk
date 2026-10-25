# 0045: MusicBrainz and Discogs IDs on the edit page, ready to paste into
Date: 2026-10-25 · Status: Accepted · Changes [0018](0018-musicbrainz-and-discogs-ids.md)

## Context
Tagwerk writes the four MusicBrainz ID fields and the three Discogs ID fields in every format ([ADR 0018](0018-musicbrainz-and-discogs-ids.md), [0033](0033-discogs-track-ids.md)), but only Fix IDs and the online lookup ([ADR 0032](0032-ids-from-the-online-lookup.md)) set them. When the lookup finds nothing sure, or the owner knows the right release better, the only way left was Advanced tags ([ADR 0039](0039-advanced-tags.md)): typing the field names by hand (`TXXX:MusicBrainz Album Id`, `musicbrainz_albumid`, `----:com.apple.iTunes:MusicBrainz Album Id`, the `UFID` frame), different in every format. The owner wants to just enter the IDs, with the fields already prepared.

## Decision
- **The edit page has a MusicBrainz section and a Discogs section**, after ReplayGain: Track (recording), Album (release), Artist, Album artist; Release, Artist, Track. Tagwerk writes each into the field the format uses, as it already does for Fix IDs; the owner never sees a field name.
- **A link works as well as an ID.** A pasted `musicbrainz.org/release/…` or `discogs.com/release/25124086-…` link (old Discogs links and language paths too) becomes its ID. The page must fit the field: a recording's link in the album field, a MusicBrainz *track* (a track on a release, not the recording) or a Discogs master is refused with a message saying what the field needs. The usual checks follow (an MBID's shape, Discogs numbers, one recording per track).
- **Same flow as every edit**: pending change → review (IDs shown as links to their pages, ADR 0032) → apply with snapshot → undo. A normal ID change takes back pending Advanced tags changes of the fields feeding it (ADR 0039).
- **An ID left as it was is never checked.** A field holding a Discogs number in a MusicBrainz field (flagged, ADR 0018) doesn't stop the owner from saving a new BPM; the section points to Fix IDs. Only what was typed is checked.
- **Several tracks**: the album and artist IDs can be set for all of them (tick *Change*); a track's own IDs (the recording, the Discogs track) aren't offered there.
- No new fields: release group, release track and work IDs stay with Advanced tags until there is a reason to add them.

## Consequences
- Setting the right release for an album takes one paste per field, no other tag editor.
- The edit page is longer; the ID sections come last before Advanced tags, after the DJ fields ([ADR 0024](0024-made-for-djs.md)).

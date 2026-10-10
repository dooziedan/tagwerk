# 0030: Wrong IDs fixed on import
Date: 2026-10-10 · Status: Accepted · Changes part of [0018](0018-musicbrainz-and-discogs-ids.md)

## Context
[ADR 0018](0018-musicbrainz-and-discogs-ids.md) added **Fix IDs** for library tracks whose MusicBrainz ID fields hold Discogs numbers (or other values), but left inbox tracks alone: they were only flagged after the import. The owner's library grows almost only through the inbox, so every import brought the wrong IDs in again.

Some taggers also write the Discogs release number with the track's position as the MusicBrainz track ID: `33199809-10` is track 10 of release 33199809. Tagwerk didn't know this form and would have removed it.

## Decision
- **On import**, wrong values in the four MusicBrainz ID fields get the same fix as **Fix IDs**: real MusicBrainz IDs stay, Discogs numbers and links move to **Discogs release ID** / **Discogs artist ID**, anything else is removed. The change is part of the import's tag write (source "Fix IDs"), with a snapshot, and undoing the import restores the old values.
- The inbox review page lists each wrong value and what the import will do with it, like the track page.
- Inbox tracks keep only some ID fields in the database, so the import reads the file's IDs at the time it plans the import. No new columns and no inbox rescan are needed.
- The fix needs no setting: nothing is lost (the Discogs numbers are kept), it is shown before the import and it can be undone. An automatic import does it too.
- `release-position` (`33199809-10`) in the track and album fields is read as a Discogs release number, in the library and on import. Only the release number is kept: Discogs has no track IDs.

## Consequences
- Library tracks are still fixed with **Fix IDs** (track page, or all of them from Home's link), as pending changes to review.
- Planning an import reads each inbox file's tags once more; cheap next to the audio analysis.

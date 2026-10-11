# 0032: MusicBrainz and Discogs IDs from the online lookup
Date: 2026-10-11 · Status: Accepted · Extends [0014](0014-online-identification.md) and [0018](0018-musicbrainz-and-discogs-ids.md)

## Context
Tagwerk writes the four MusicBrainz ID fields and the two Discogs ID fields in every format since 0.9, but only **Fix IDs** changed them, and it only moves or removes wrong values ([ADR 0018](0018-musicbrainz-and-discogs-ids.md)). The online lookup ([ADR 0014](0014-online-identification.md)) already received the IDs (MusicBrainz' recording search, AcoustID's recordings, Discogs' releases) and threw them away. Every track that *is* on MusicBrainz or Discogs should carry its IDs; edits and bootlegs simply have none, and that is fine (issue #48).

IDs are stricter than text values: a wrong ID is worse than none, because Navidrome and Picard trust it.

## Decision
- **The sources hand over the IDs they get.** MusicBrainz: the recording, its artists, and the release Tagwerk already picks for the album (official, earliest, no compilations) with its album artists. AcoustID: the recording and its artists (it names release groups, not releases, so no album ID). Discogs: the release. Two extra requests, each only for a source's best match and only when that source was just asked: the Discogs release itself for its **artist IDs**, and the MusicBrainz release's links for the **Discogs release** it points to (only with Discogs switched on).
- **Only sure IDs are suggested**, and **only for empty ID fields**; existing IDs are never replaced. While a MusicBrainz field holds something that isn't an MBID, no MusicBrainz ID is suggested: Fix IDs first.
  - **The recording** is sure when AcoustID recognised the sound clearly (90 % or more), or when AcoustID and MusicBrainz name the same recording. Two sources agreeing on the title is not enough. The artist IDs come with the recording.
  - **The album IDs** only from MusicBrainz' release of that same recording, and only when its title is the track's album (its own tag or a sure suggestion). Never from a compilation.
  - **Discogs** is the only source with Discogs IDs, so "two sources agree" means: the MusicBrainz release links to this Discogs release, or the Discogs release is the track's album and its label or catalog number agrees too (the track's own tags or sure suggestions, never Discogs alone). Of several pressings, the one matching both label and catalog number wins; if none clearly does, no Discogs ID. Digits only, as Fix IDs writes them.
- **Library tracks**: sure IDs become pending changes by themselves (source "Found online"), with the other sure values. Final tracks get nothing (locked).
- **Inbox tracks**: sure IDs are written on import, into ID fields that are empty once the import's ID fixes ([ADR 0030](0030-ids-fixed-on-import.md)) are done. The review page lists them with the reason. Inbox tracks don't keep every ID field, so the import reads the file's IDs, only when there is an ID to write.
- **"Use these values"** also takes over the result's IDs, again only for empty ID fields (library: pending changes; inbox: the owner's values, written on import).
- **Seen before written**: the Online sources card links the IDs a result found; the Changes page and the inbox review page show each ID as a link to its MusicBrainz or Discogs page, so the owner can check where it points. IDs are listed after the DJ fields and in small type, so they don't crowd BPM, key and genre ([ADR 0024](0024-made-for-djs.md)).
- No setting: IDs are always suggested when sure, like every other online value.
- (Added in [ADR 0033](0033-discogs-track-ids.md): the Discogs track ID, from the release's tracklist.)

## Consequences
- Tracks looked up before this change have no IDs in their stored results; *Look up again* (or the 30-day refresh) brings them.
- An AcoustID match alone gives no album ID; the album ID needs MusicBrainz' search to find the same recording.
- A lookup can take up to two more requests (about a second each, within the sources' rate limits).
- Tests use saved answers: real MusicBrainz ones and AcoustID/Discogs answers made up in their real format.

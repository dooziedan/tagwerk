# 0031: Store genres matched against the genre map
Date: 2026-10-11 · Status: Accepted · Changes part of [0014](0014-online-identification.md)

## Context
Online lookups send genres in the source's own words. The genre map already tidied them, but only as a whole name: iTunes files Drum & Bass under its store category **"Jungle/Drum'n'bass"**, which isn't in the map, so it became a pending change as it was. The map knows both parts ("Jungle" is a subgenre of Drum & Bass, "Drum'n'Bass" a spelling of it); it just never looked at them. Discogs' style "Drum n Bass" for the same track was tidied to "Drum & Bass", so the two sources didn't agree either.

## Decision
- **Every genre from an online source is matched against the owner's genre map** before anything uses it: the Online sources card, "Use these values" (inbox and library) and the sure values that become pending changes. One place does it (`identify.results()`, with `GenreMap.match`).
- **Combined store categories are matched part by part** (split at `/`): when the map knows every part and all parts belong to the same main genre, the match is that main genre: "Jungle/Drum'n'bass" → "Drum & Bass". Not "Drum & Bass; Jungle": the category means "one of these", and most Drum & Bass tracks aren't Jungle.
- Otherwise the genre is tidied like any other (spelling, main genre first) or stays as the source wrote it: "House/Techno" (two main genres) and "Electronic/Drum & Bass" ("Electronic" isn't in the map) aren't guessed. A whole name in the map always wins over its parts ("UK Garage / Bassline").
- The stored answers keep the source's spelling, so a changed genre map applies to them right away, without looking up again.

## Consequences
- Two sources now agree more often on a genre, so it is sure (and staged for library tracks with an empty genre) more often.
- Categories the map doesn't cover still arrive as sent; the owner adds a line to the genre map (`R&B = R&B/Soul`) and it applies to every result at once.
- Genres in the files are unchanged: scans store tags as found, and the clean-up suggestions only use whole names from the map.

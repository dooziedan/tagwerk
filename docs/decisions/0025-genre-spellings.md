# 0025: One genre, however it is spelled
Date: 2026-10-09 · Status: Accepted

## Context
The owner's library spells one genre in several ways: "Drum & Bass", "Drum and Bass", "Drum And Bass", "DnB". The Statistics page counted each spelling as its own genre, with its own percentage. The track list's genre filter, however, ignored upper/lower case (SQLite's `LIKE`), so clicking "Drum and Bass" also listed "Drum And Bass" tracks: the number and the list disagreed. The genre map (Settings → Genre map) already knows the spelling variants, but only used them for inbox and lookup suggestions.

## Decision
- **One rule for counting and filtering**: a genre matches regardless of upper/lower case, and with every spelling the genre map lists for it (`GenreMap.key`, `GenreMap.spellings`). The Statistics genre chart, "Set-ready by genre", the heat map and the track list's genre filter all use it, so a number still opens exactly its tracks. The bar is labelled with the most used spelling (for a genre in the map: the map's name).
- **The tags stay as found** (scans store what's on disk). Unifying them is the owner's choice on a **Genre spellings** page: per genre, pick the spelling to keep (the map's name suggested, else the most used one), tick the genres to merge, and Tagwerk stages pending changes (source "Genre spellings merged"). Writing goes through review → apply as always; final tracks are skipped.
- A merge replaces only the merged genre inside a multi-genre tag and keeps the others and their order; a genre that ends up twice is kept once. It builds on a genre change that is already pending instead of discarding it.
- Subgenre rules (`>`) don't merge: "Liquid" stays its own genre in the chart.

## Consequences
- Case folding is ASCII only, like SQLite's `LIKE`; "Électro" and "électro" stay two genres.
- Picking a spelling other than the genre map's name doesn't change the map: inbox suggestions keep using the map. The owner changes the map in Settings if they prefer another name.

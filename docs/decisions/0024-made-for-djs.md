# 0024: Made for DJs (no Collector mode)
Date: 2026-10-09 · Status: Accepted · Supersedes [0006](0006-modes.md)

## Context
Tagwerk had two modes ([ADR 0006](0006-modes.md)): DJ (BPM, key, label, set-readiness, audio quality) and Collector (albums, decades, lyrics, ReplayGain). The owner uses Tagwerk only as a DJ, and the second mode doubled the work: every page, test and new feature (e.g. whether a single and an album version count as duplicates) had to be thought through twice.

## Decision
- **One way of working: a DJ's.** The mode setting, the Collector view of Statistics (decades, lyrics), the Collector order of the edit form and the inbox review, and the mode question in the setup wizard are gone. Every page shows what a DJ needs: BPM, key, genre, label, set-readiness and audio quality first; album fields further down.
- Nothing stored changes: tags are read and written as before, and album fields, ReplayGain and lyrics stay visible where they are useful (the track page's "Album and more", the edit form).
- Old databases keep a `mode` row in the settings table; it is ignored.

## Consequences
- Simpler code and tests; new features are designed once, for DJ use.
- People who manage a collection by albums are not the audience any more.

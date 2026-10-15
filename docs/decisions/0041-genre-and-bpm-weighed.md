# 0041: Online genre and BPM are weighed together and checked against the audio
Date: 2026-10-13 · Status: Accepted; the tempos moved to their own setting in [0042](0042-bpm-ranges.md)

## Context
Stores list drum & bass at half time: Beatport and Deezer often say 87 for a 174 track. For the owner, drum & bass is never under 160 BPM. The audio decision (ADR 0017) already settled 87 or 174 by the genre, but online BPMs slipped through elsewhere:
- a track not analysed yet got the stores' 87 as a sure suggestion or pending change when two stores agreed;
- "Use these values" took the store's 87 as it was;
- a track without a genre tag only got a genre for the tempo when two sources agreed on it, so Beatport alone saying "Drum & Bass" didn't count, and the audio's 87 plus Beatport's 87 made a "sure" 87;
- an online 87 staged before the analysis stayed, because the audio only replaced its own earlier values.

And the genres themselves weren't checked: Deezer and iTunes give a whole album one broad genre, and two of them saying "House" for a 174 BPM track won over Beatport's "Drum & Bass".

Some DJs prefer half time for a genre (dubstep at 70), so the tempos can't be fixed in code.

## Decision
- **Tempos live in the genre map** (Settings → Genre map) as rules like `Drum & Bass: 160-185 BPM`. Subgenres share their main genre's tempo (Liquid, Neurofunk); store categories match a tempo genre they contain as a whole word ("Melodic House & Techno" → House). The built-in map has the tempos that were in the code before. An own map saved before tempo rules existed keeps the built-in tempos, and Settings shows them added at the end, ready to change. Preferring half time is one line: `Dubstep: 70-75 BPM`.
- **Online BPMs are read at the genre's tempo** (`app/tempo.py`, `tempo.fold`): 87 with a 160-185 genre is 174. The genre is the one the track will have (the owner's value, a pending change, the tag, else the weighed online genre); for "Use these values" and the online box the result's own genre first, since it is taken too. The online box shows why ("Beatport says 87: Drum & Bass is 160-185 BPM").
- **Online genres are weighed** (`identify.weigh_genre`): sources saying the same genre add up by how well they matched; Beatport's counts double (it files every single track under a DJ genre). With an analysis, a genre whose tempo the audio doesn't hear (not even at half or double time) loses to one it does, is never sure, and the suggestion says why ("not House (Deezer + iTunes): the audio hears 174 BPM"). Sure still needs two agreeing sources.
- **The audio decision uses the weighed online genre** when the track has no genre with a tempo, but only if the audio fits it.
- **The audio replaces an online BPM staged earlier** (never the owner's own edit).

## Consequences
- All BPM paths (suggestions, pending changes, "Use these values", the audio decision) follow the same tempo rules.
- Library decisions are worked out again after the next scan or apply; a track whose genre changes on the Changes page gets its BPM decided again as before.
- A genre without a tempo rule ("Electronic", "Pop") settles nothing; the owner can add rules for genres they play.
- Planned for the next release: the tempo ranges get their own Settings section instead of lines in the genre map (roadmap).

# 0042: BPM ranges are their own setting
Date: 2026-10-15 · Status: Accepted

## Context
Since ADR 0041 each genre's usual tempo settles half or double time (a store's 87 for drum & bass becomes 174) and rules out genres the measured tempo doesn't fit. The tempos were lines in the genre map's text (`Drum & Bass: 160-185 BPM`), mixed in with spelling and subgenre rules. Changing one meant finding its line in a long text box and keeping the format right; a built-in map that was never saved didn't show its tempos as something to change.

## Decision
- **Settings → BPM ranges** is its own section: one row per genre with its lowest and highest BPM, a × to remove it, an empty row to add one, and *Back to the built-in ranges*. Each row says which subgenres share it ("with Liquid, Liquid Funk, Liquid Drum & Bass +6"), taken from the genre map. Rows are sorted by tempo.
- **Stored on their own** (`Preferences.bpm_ranges`: genre → [low, high]). `None` means the built-in ranges (`tempo.DEFAULT_RANGES`), and own ranges equal to them are stored as `None` too, so they keep up with updates, like the genre map.
- **The genre map no longer holds tempos.** Tempo lines in a map saved with 0.26 move to the ranges when the preferences are read: without own ranges they become the ranges (they were all of them), else they're added. A tempo line typed into the map later is moved the same way, so nothing the owner writes is lost.
- **Checked when saved:** every row needs a genre and two numbers between 40 and 300 (comma or dot); a genre listed twice is a mistake. A mistake keeps the rows as typed, with one message.
- **Takes effect right away:** after saving, the library's BPM decisions are worked out again (`analysis.refresh_all`, about 2 s at 20,000 tracks). While a job runs this waits, as the job does it at its end.
- How a range is used doesn't change (ADR 0041): subgenres share their main genre's range, spellings from the genre map count, store categories match a genre they contain as a whole word.

## Consequences
- The ranges and the old line format live in `app/tempo.py`, which imports nothing from the app, so `genres` and `preferences` can both use them without an import circle (ADR 0040).
- `genres.of(prefs)` builds the genre map in use from both settings; `genres.from_text` and `with_tempos` are gone.
- `PUT /api/settings` takes `bpm_ranges` like any other preference; odd entries are left out.

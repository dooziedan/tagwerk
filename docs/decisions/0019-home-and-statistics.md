# 0019: Home and Statistics instead of one dashboard
Date: 2026-10-07 · Status: Accepted

## Context
The start page was a dashboard of statistics: counts, missing tags, formats, genres, keys, tempo. That is interesting once, but the owner opens Tagwerk because new music arrived or something needs fixing. The owner also wanted statistics that matter to a DJ: a key and tempo grid, tracks per release year, library growth. Tempo per genre was rejected: in electronic music each genre's tempo is standardized, so it shows nothing new.

## Decision
- **Home** (`/`, `app/home.py`) answers "what needs me?": the inbox (ready / needs help), pending changes, running jobs, problems worth a look (each a number linking to its tracks), the 10 most recently added tracks, and a few headline numbers. When nothing needs the owner, it says so.
- **Statistics** (`/stats`, Library menu) keeps every chart from before and adds:
  - a **heat map** of any two of key, tempo (5-BPM steps), release year, year added, genre (top 10; a track with two genres counts in both) and format, opening on key × tempo. One teal ramp from light to dark (dark to light in dark mode), as theme tokens; the count is printed in each cell and every cell links to its tracks,
  - **library growth** (tracks added per month, 24 months, and per year),
  - **set-ready by genre**, **track length**, **top labels**, **top artists**.
- **When a track was added** is a new column `track.added_at`: the import for tracks imported from the inbox (the file keeps its download date), otherwise the file's date when a scan first found it. Existing rows get the import date if there is one, else the earliest of the file date and Tagwerk's first change to the file.
- "Set-ready" (title, artist, genre, BPM, key, cover) is one condition in `app/library.py`, shared by Home, Statistics, the track list and the Final check.
- The rule that every number matches its track list now covers every heat-map cell for every pair of axes.

## Consequences
- Home builds the inbox summary (suggestions per track) on every visit; with a very large inbox it may need caching.
- The added date of tracks from before 0.10 is an estimate; tracks Tagwerk imports from now on have the exact date.

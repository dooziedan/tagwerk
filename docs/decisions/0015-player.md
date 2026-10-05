# 0015: Play bar, and swapping pages in place
Date: 2026-10-05 · Status: Accepted

## Context
The owner wants to listen to tracks inside Tagwerk: a simple bar (play/pause, a progress bar to jump around, stop), no queue, no details. It must keep playing while moving between pages.

## Decision
- **Audio routes** in `app/routes/player.py`: `/tracks/{id}/audio` and `/inbox/{id}/audio` serve the file read-only with range requests (jumping works). The path must stay inside the music or import folder.
- **Formats browsers can't play** (AIFF, mostly ALAC): `…/audio.mp3?start=SECONDS` lets ffmpeg convert to MP3 (320 kbit/s) while streaming; ffmpeg stops when the listener stops or jumps. Jumping restarts the conversion at that point. `player.js` asks the browser with `canPlayType` and picks the file or the MP3.
- **Keep playing across pages with htmx boost**: `<body hx-boost="true">`; all page content sits in `#page`, the play bar and `player.js` outside it. A small `htmx:beforeSwap` handler aims every boosted link and form at `#page` (swap `outerHTML`, `select #page`), and shows 4xx pages (form errors are 422). The `/docs` link is not boosted.
- **Volume** goes through a Web Audio gain node that glides to each new level (~30 ms), so fast slider moves are not heard as steps; the slider is squared to feel even. Falls back to `audio.volume` without Web Audio.
- **Touch screens** (`hover: none`: phones, tablets) get no volume control: the hardware buttons set the volume (iOS ignores `audio.volume` anyway). Web Audio is skipped there, because iOS silences it with the mute switch while a plain audio element keeps playing.
- **Space** pauses and resumes while a track is loaded, except while typing or on controls where space already acts (buttons, links).
- Polling partials that used `HX-Refresh` (scan, changes, inbox jobs) use `reload_page()` in `app/navigation.py`, which sends `HX-Location` with the same target, so a finished job doesn't stop the music. Without `HX-Current-URL` it falls back to a full reload.
- Page scripts must be safe to run many times (they run on every swap): global listeners register once. Page HTML must be balanced: a stray closing tag would close `#page` early (`tests/test_html.py` checks every page).
- Confirmations use a `<dialog>` in `base.html` (`data-confirm` on a form or submit button) instead of `confirm()`, which some browsers block; it stops the submit before htmx sees it.
- No queue, no autoplay of the next track, no state kept across a browser reload: simple on purpose.

## Consequences
- Pages are no longer fully reloaded; new inline scripts must not assume a fresh page.
- Converting for playback uses CPU while a converted track plays.

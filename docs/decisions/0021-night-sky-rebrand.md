# 0021: The night-sky look (visual rebrand)
Date: 2026-10-07 · Status: Accepted · Supersedes [0008](0008-design-language.md)

## Context
The owner wants to enjoy Tagwerk visually: a very specific look, even if it asks more of the
client's hardware. Main inspiration is the website of Orbit Stage, the owner's drum & bass
collective (deep near-black sky, layered stars, indigo light, one warm gold, wide display caps,
orbit rings). SoulSync (a self-hosted music tool) lends its page and object design: a sidebar,
a header panel with big numbers, ring gauges, cover cards. Plus a touch of glassmorphism. Not
wanted: SoulSync's constant movement. Calm and Pop (ADR 0008) are replaced, not kept beside it.
Research, mood board and mock-ups came first; the owner chose every option below.

## Decision
- **One dark look**, no light mode. The Appearance (system/light/dark) and Theme (Calm/Pop)
  settings are gone; old rows in the settings table are ignored.
- **Palette** (tokens in `theme.css`): space `#030308` → `#1e1b4b`, indigo `#818cf8`/`#a5b4fc`
  for lines, links and most charts, **gold `#f5c542`** for buttons, the current page and final
  tracks; one hue per chart (rose missing, sky formats, gold genres, violet decades); status
  colours (sure, check, problem) always with a word. Contrast is measured against glass over the
  brightest nebula spot (text ≥ 4.5:1, marks ≥ 3:1).
- **Sky**: nebula glows plus three layers of `box-shadow` stars (generated CSS, no images),
  drifting very slowly ("calm": 600–1500 s per 2400 px), a few breathing bright stars, depth on
  pointer and scroll, a short warp on page change. It sits outside `#page`, so hx-boost swaps
  never restart it.
- **Glass**: smoked glass for cards and page heads, frosted glass for the sidebar, play bar and
  menus; `backdrop-filter` only inside `@supports`, with solid fallbacks; bars that float over
  content are opaque enough to read without blur.
- **Type**: Orbitron (SIL OFL, shipped unmodified) only for the wordmark and page titles;
  everything that is read (text, tables, numbers, buttons, tag values) stays Inter.
  The owner's rule: fancy fonts must not hurt readability.
- **Layout**: a grouped sidebar on wide screens (≥ 1100 px), a floating glass bar with a menu on
  narrow ones; every `.page-head` becomes a glass hero with a planet rising at its bottom edge.
- **Lighter effects** (Settings → Effects): no blur, drift, twinkle or glow, for weak devices.
  `prefers-reduced-motion` gives a still version; forced colours drop the effects.
- **Logo**: the luggage tag with level bars stays, now in the indigo planet gradient.
- **Key wheel**: standard Camelot colours stay; empty keys are dark instead of grey.

## Consequences
- More GPU work than before (blur over a slowly moving sky). The Lighter effects switch is the
  answer when a device struggles.
- One look to test: `scripts/screenshots.py` checks dark only, three engines, desktop and phone.
- Translucent steps of palette colours are written as `rgba()` in `app.css` (no `color-mix()`).
- Orbit Stage's own font (all rights reserved), logo and artwork are not used.

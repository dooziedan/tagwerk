# 0008: Two themes from one palette, contrast-checked tokens, no newer CSS
Date: 2026-10-04 · Status: Accepted

## Context
Tagwerk used Pico's default blue, had no logo, and one chart broke in the owner's Safari because it relied on `color-mix()`. The owner chose a "clean & calm" direction, a five-colour palette, and wanted to pick between a one-colour theme and a colourful one.

## Decision
- Two themes, **Calm** (one accent) and **Pop** (full palette), each with light and dark. Theme and appearance are preferences in `/config`.
- All colours are **tokens** in `app/static/theme.css`, overriding Pico's variables. Each value documents its measured contrast; text ≥ 4.5:1, marks ≥ 3:1.
- The Camelot wheel keeps the **standard Camelot colours in every theme** (owner's request), tuned for readable labels.
- **No newer CSS** (`color-mix()` etc.) for essentials; chart colours are SVG attributes.
- Cross-browser screenshots (Chromium, Firefox, WebKit) run in Playwright's Docker image before UI releases.

## Consequences
- New pages only use tokens and existing building blocks, so both themes work automatically.
- A third theme would be one more token block in `theme.css`.

# Design language

Tagwerk is calm and functional: a well-made tool for looking after a music library. Two themes, chosen in **Settings → Theme**, each in light and dark (**Settings → Appearance**: follow system, light, dark).

| | **Calm** (default) | **Pop** |
|---|---|---|
| Idea | One accent colour, quiet and focused | The full palette, every section has its own colour |
| Buttons | Verdigris | Burnt Peach |
| Links | Verdigris | Verdigris (light), Jasmine (dark) |
| Charts | all Verdigris | tempo Verdigris, missing tags Burnt Peach, formats Sandy Brown, genres Jasmine, decades Charcoal Blue |
| Headline tiles | plain | colour stripe per tile |

## Palette

| Name | Hex | Used for |
|---|---|---|
| Charcoal Blue | `#264653` | brand, headings, dark backgrounds (`#0f1f26`, cards `#16303a`) |
| Verdigris | `#2A9D8F` | the Calm accent, charts |
| Jasmine | `#E9C46A` | Pop accent (links in dark mode, genres) |
| Sandy Brown | `#F4A261` | Pop accent (formats) |
| Burnt Peach | `#E76F51` | Pop buttons, missing tags |

All values live in [`app/static/theme.css`](../app/static/theme.css) as CSS variables (Pico's `--pico-*` plus Tagwerk's `--tw-*`). Pages never hard-code colours.

## Contrast rules

- Text at least **4.5:1**, chart marks at least **3:1** against their background. Measured ratios are noted next to each value in `theme.css`.
- Light colours (Jasmine, Sandy Brown) are too pale on white. In light mode, readable uses get darker steps: `#A9851B`, `#D27A2C`, `#D35539`, `#1F7A6F`.
- One chart = one colour. Colours never have to be told apart within a chart; values are always printed next to bars.

## Camelot wheel

The key wheel uses the **standard Camelot colours in every theme** (hue running clockwise from 1 aqua-green through orange at 5 and blue at 10 to cyan at 12), minor lighter than major, empty keys grey. Shades are tuned so the dark labels reach 4.5:1 on every segment; a test checks all 24.

## Logo

A luggage tag (pointed left, with a punched hole) holding four level bars: [`app/static/logo.svg`](../app/static/logo.svg). Pop: Charcoal Blue tag with palette-coloured bars. Calm: Verdigris tag with plain bars. Also exported as favicon, Apple touch icon and the Unraid icon (`unraid/tagwerk-icon.png`).

## Building blocks

Pico CSS provides the base components; `app/static/app.css` adds Tagwerk's: headline tiles (`.kpi`), bar lists (`macros.html` → `bars(..., tone=…)`), chips (`.chip`), badges (`.badge`), the key wheel, track tables, the brand mark.

## Browser support

Must work in current Chrome/Edge/Brave, Firefox and **Safari**.

- **No `color-mix()`** or similar newer CSS for anything essential: the owner's Safari didn't apply it (white-on-white wheel in v0.3.1). Chart colours are SVG attributes.
- Every release is checked with [`scripts/screenshots.py`](../scripts/screenshots.py): the main pages in Chromium, Firefox and WebKit (Safari's engine), both themes, light and dark, desktop and phone, failing on browser errors.

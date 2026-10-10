# Architecture decision records

Short notes on *why* important choices were made, so future changes can be judged against the original reasons.
A new decision gets the next number. A decision that is replaced is marked "Superseded by NNNN", not deleted.

| # | Decision | Status |
|---|---|---|
| [0001](0001-tech-stack.md) | Python, FastAPI, SQLite, server-rendered pages with htmx | Accepted |
| [0002](0002-unraid-deployment.md) | Single container, Unraid conventions, images on GHCR | Accepted |
| [0003](0003-review-before-write.md) | Files are only changed through review → apply, with snapshots | Accepted |
| [0004](0004-license.md) | License AGPL-3.0-or-later | Accepted |
| [0005](0005-reading-tags.md) | One common tag format, Picard conventions, honest about bad data | Accepted |
| [0006](0006-modes.md) | DJ and Collector modes change the view, never the data | Superseded by 0024 |
| [0009](0009-writing-tags.md) | How tags are written and undone | Accepted |
| [0008](0008-design-language.md) | Two themes from one palette, contrast-checked tokens, no newer CSS | Accepted |
| [0007](0007-import-inbox.md) | Import inbox with opt-in automatic tagging (amends 0003) | Accepted |
| [0010](0010-new-genre-folders.md) | New genre folders only after review (amends 0007) | Accepted |
| [0011](0011-inbox-duplicates-and-trash.md) | Duplicates in the inbox, and an inbox trash | Accepted |
| [0012](0012-final-tracks.md) | Final tracks, and renaming only when marking final | Accepted |
| [0013](0013-convert-to-aiff.md) | Converting to AIFF, with originals kept aside | Accepted |
| [0014](0014-online-identification.md) | Online identification of inbox tracks | Accepted |

Template:

```markdown
# NNNN: Title
Date: YYYY-MM-DD · Status: Proposed | Accepted | Superseded by NNNN

## Context
What problem or situation forces a decision?
## Decision
What we chose.
## Consequences
What gets easier, what gets harder.
```
| [0015](0015-player.md) | Play bar and page swapping (hx-boost) | Accepted |
| [0016](0016-private-data-cleanup.md) | Removing private ID3 data (PRIV) through Changes | Accepted |
| [0017](0017-audio-analysis.md) | BPM and key from the audio (Essentia) | Accepted |
| [0018](0018-musicbrainz-and-discogs-ids.md) | Fixing MusicBrainz ID fields; Discogs IDs in their own fields | Accepted |
| [0019](0019-home-and-statistics.md) | Home and Statistics instead of one dashboard | Accepted |
| [0020](0020-tagwerks-work.md) | Tagwerk's work, and recording where values came from | Accepted |
| [0021](0021-night-sky-rebrand.md) | The night-sky look (visual rebrand), replaces Calm and Pop | Accepted |
| [0022](0022-library-duplicates.md) | Duplicates in the library: stored groups, shown side by side, never deleted | Accepted |
| [0023](0023-library-trash.md) | A trash for library copies, emptied only by the owner | Accepted |
| [0024](0024-made-for-djs.md) | Made for DJs: no Collector mode | Accepted |
| [0025](0025-genre-spellings.md) | One genre, however it is spelled: counted and filtered as one, merged on review | Accepted |
| [0026](0026-mix-names.md) | Mix names with capital letters: one rule for inbox and library, fixed on review | Accepted |
| [0027](0027-queued-trash-decisions.md) | Trash decisions on the Duplicates page wait for Apply | Accepted |
| [0028](0028-replaygain.md) | ReplayGain fields, read and written in every format (Opus: R128) | Accepted |
| [0030](0030-ids-fixed-on-import.md) | Wrong IDs in MusicBrainz fields fixed on import; Discogs `release-position` IDs | Accepted |

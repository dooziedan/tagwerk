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
| [0006](0006-modes.md) | DJ and Collector modes change the view, never the data | Accepted |
| [0009](0009-writing-tags.md) | How tags are written and undone | Accepted |
| [0008](0008-design-language.md) | Two themes from one palette, contrast-checked tokens, no newer CSS | Accepted |
| [0007](0007-import-inbox.md) | Import inbox with opt-in automatic tagging (amends 0003) | Accepted |
| [0010](0010-new-genre-folders.md) | New genre folders only after review (amends 0007) | Accepted |

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

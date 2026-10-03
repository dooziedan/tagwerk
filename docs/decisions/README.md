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

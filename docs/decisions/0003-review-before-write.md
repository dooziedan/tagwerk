# 0003: Files are only changed through review → apply, with snapshots
Date: 2026-10-03 · Status: Accepted

## Context
A tagging tool can damage a whole music library with one wrong click or a bad lookup match. The library is also used by Navidrome, so mistakes show up immediately.

## Decision
- Edits and metadata lookups create **pending changes** in the database only.
- A **review** page shows old → new for each field and file before anything is written.
- **Apply** first stores a **snapshot** of the current tags, then writes. Any applied change can be undone from its snapshot.
- Development and tests use a copy of a few albums, never the real library.

## Consequences
- One extra click for the user, in exchange for safety and undo.
- The database must track pending changes and snapshots (Phase 2).

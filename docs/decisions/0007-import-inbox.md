# 0007: Import inbox with opt-in automatic tagging
Date: 2026-10-04 · Status: Accepted (amends 0003)

## Context
The owner wants Tagwerk to handle new music on its own as far as possible: tracks from record pools, stores, promos and downloads arrive regularly, and tagging each one by hand doesn't scale. [ADR 0003](0003-review-before-write.md) says files are only changed after the owner reviewed the change.

## Decision
- New music goes to a separate **import inbox** (its own container path), not into the library. Navidrome never sees untagged tracks.
- Tagwerk runs a pipeline on inbox tracks: read tags → parse filename → clean-up rules → online identification → audio analysis → a proposed value with a **confidence** per field.
- **How independently Tagwerk works is the owner's choice**, made in a first-run setup wizard and changeable in Settings:
  - *Always ask:* nothing is written until the owner approves (one click can approve many).
  - *Auto-apply confident results:* values above the confidence threshold are written without asking; uncertain tracks wait on the "needs your help" page.
- Even in automatic mode, the old tags are **snapshotted first**, so every change can be undone. This is what remains of ADR 0003 for the inbox.
- Automatic writing applies to **inbox tracks only**. Changes to tracks already in the library always go through review (ADR 0003 unchanged there).
- Finished tracks are moved into the library by the owner's folder pattern: copy, verify, then delete the original.

## Consequences
- The writing engine (v0.6) must exist before the inbox (v0.7).
- Confidence scoring has to be honest. Edits, bootlegs and promos rarely match online sources, so they will often need the owner's help.
- A bad automatic rule could touch many files. Undo per track and a clear activity log on the inbox page are required.

# 0027: Trash decisions on the Duplicates page wait for Apply
Date: 2026-10-09 · Status: Accepted

## Context
On the Duplicates page, **Move to trash** moved the copy at once and reloaded the page with the trash list opened; **Use** switched to a view of the one group. Going through many groups meant losing one's place after every click. The owner wants to make all decisions on the page first, tags and trash alike, and have them carried out together when they apply.

## Decision
- **Move to trash queues the copy** as a pending change with the field `trash` (label "Move to trash", source "Duplicates page"); its value is the copy kept instead. The file stays where it is. **Don't trash** removes the mark. On the Changes page the decision is listed with the tag changes and can be unticked or discarded like them.
- **Applying writes the tag changes first, then moves the marked copies** to the library trash (`duplicates.trash_copy`, with the same checks as before, again at apply time). Other pending changes of a marked copy aren't written; its row goes with it. Trash moves aren't part of the change set, as before: the trash is their record, with Restore ([ADR 0023](0023-library-trash.md)). A move that fails (e.g. the copy to keep is gone) stays queued.
- **One copy always stays**: the copy to keep is never marked; marking a copy drops a mark on the copy kept instead, and all marked copies of a group point at the same copy to keep. The page shows that copy as "Keep", so the page and Apply agree.
- **Every button brings the owner back to where they were**: same filter and page, scrolled to the group (`#group-N`); one-off notes aren't carried along. "Keep this one instead" still opens the group on its own.

## Consequences
- A copy marked for the trash counts as having a pending change: it can't be converted or marked final until the mark is applied or removed.
- Nothing happens in the music folder before Apply, so the page needs no job lock to mark copies; applying runs as the usual write job.

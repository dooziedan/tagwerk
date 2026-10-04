# 0010: New genre folders only after review
Date: 2026-10-04 · Status: Accepted (amends 0007)

## Context
With genre folders, an imported track used to get a folder named after its main genre. With no main genres ticked, any genre created a new folder on its own: one oddly tagged track ("Rock", "Electronica", a typo) and the library had a new top-level folder, which the owner sees in the file explorer and in Navidrome. The owner wants to decide which genre folders exist.

## Decision
- **Tagwerk never creates a genre folder on its own.** On import, a track goes into its genre folder only if the owner chose it: a ticked main genre, or (with none ticked) a genre folder that already exists in the library. Everything else goes to `_Unsorted`.
- The **Changes page proposes** one change per main genre of the tracks in `_Unsorted`: the folder to create and every file that would move into it (`_Unsorted/x.mp3 → Rock/x.mp3`).
- **Create folder and move** creates the folder, moves the files with their exact filenames (a `.lrc` lyrics file with the same name moves along) and, if the owner ticked main genres, adds the genre to them so later imports go there directly.
- **Keep in _Unsorted** stops proposing that genre (stored in the preferences; "Propose folders again" undoes it).
- Moving is recorded in the history like any other change (`changeset.kind = "folder"`). Undo moves the files back and removes the folder and the added main genre again, if Tagwerk added them. A folder is only removed when it is empty.
- Moves inside the library are renames on the same share: the file contents are never rewritten, so no snapshot is needed. A file that already exists at the destination is never overwritten.

## Consequences
- With no main genres ticked, the first track of a genre waits in `_Unsorted` until the owner agrees: one click more, in exchange for no surprise folders.
- These moves change paths that Navidrome already knows. Tagwerk asks Navidrome to rescan afterwards; whether play counts and ratings follow a moved file depends on Navidrome (see the roadmap note on moved files).
- Only the genre layout gets proposals. A custom pattern with `{genre}` still creates folders as before.

# 0046: Adopted tracks stay the same song in Navidrome: their import goes in two steps
Date: 2026-10-30 · Status: Accepted · Changes [0044](0044-releasomat-area.md) (its risk "Navidrome IDs and play counts")

## Context
Adopt ([ADR 0044](0044-releasomat-area.md)) moves a Releasomat download into the import inbox
(`/import/Releasomat/…`). There it is identified and its tags are improved (title, album, IDs, BPM,
key, genre), and the import moves it into the library. The owner wants such a track to **stay the
same song in Navidrome**: in every playlist (Releasomat's and the owner's own), with its plays,
stars and rating, and without a second song. Until now Navidrome usually made a new song, and the
old one stayed behind as *missing*.

**How Navidrome recognises a moved file** (0.55 and later; tried on 0.64.2 for Releasomat's
[ADR 0010](https://github.com/dooziedan/releasomat/blob/main/docs/decisions/0010-adopted-songs-stay-the-same-song.md)):
when a file disappears, its song is marked missing. It is kept (with `Scanner.PurgeMissing` =
`never`, the default), hidden, and stays in its playlists. When a file turns up with the same
**persistent ID** (PID), it takes over the missing song: same ID, playlists, plays, stars, rating.
The default `PID.Track` is `musicbrainz_trackid|albumid,discnumber,tracknumber,title`, and the album
ID is built from album artist, album, album version and release date. Navidrome's
`musicbrainz_trackid` is the MusicBrainz **release track** ID; the recording ID that Releasomat
writes (`MUSICBRAINZ_TRACKID`) isn't part of it. Tried with a download in a playlist, starred,
rated and played:

| Changed in the inbox | Same song? |
|---|---|
| genre, BPM, key; a recording ID added; FLAC converted to AIFF with the same tags | yes |
| title and album (with or without a MusicBrainz ID) | **no**: a new song, the old one stays missing |
| the same, **in two steps**: moved unchanged, scanned, then the tags changed in place and scanned again | yes |

Tagwerk's import writes the tags first and moves the file second, so improving the title or album
breaks the match. Renaming, converting and better copies already wait for Navidrome for the same
reason ("Navidrome first", [ADR 0012](0012-final-tracks.md), [0013](0013-convert-to-aiff.md),
[0037](0037-better-copies.md)).

## Decision
- **Which files**: inbox tracks that were adopted from Releasomat (an adoption record that is still
  *adopted*, for the same inbox path), when Navidrome is set up and the import has tags to write.
  Every other file imports exactly as before.
- **Three steps**, in the import job:
  1. The usual checks, then the file **moves with the tags it has** (copy, verify, remove from the
     inbox) to the place its new tags give it. Its filename stays, as always.
  2. **Navidrome scans and lists it there.** A scan already running would ignore Tagwerk's request,
     so Tagwerk waits for it, then starts its own and waits until Navidrome's last scan time
     changes (up to 3 minutes). Then it looks for the file with Navidrome's search (`search3`): a
     song with the file's title (or filename, without a title tag), its exact size and extension.
  3. **The new tags are written into the file at its library place**, with a snapshot, and the track
     joins the library. The rescan that follows every import lets Navidrome read the new tags in
     place, where it keeps the song.
- **Listed, not only scanned.** The scan time alone could count a scan that began before the move.
  Navidrome's Subsonic API can't tell a song's real path (it makes one up from the tags), and its
  own API, which can, needs the password itself for its login. Tagwerk keeps sending only the
  salted token, so the title, exact size and extension stand in for the path. Searches skip songs
  whose file is gone, so the old song in Releasomat's folder can't answer for it.
- **One scan per import.** Other tracks import first, as before; then the adopted ones move, one
  wait follows for all of them, then their tags are written. The automatic import works the same,
  inside the inbox check. The job holds the job lock all the while, so no scan, inbox check or
  other write runs in between.
- **Never blocked by Navidrome.** Without Navidrome set up, nothing changes (tags first). When it
  doesn't answer, its scan doesn't finish in time, or it doesn't list the file, the tags are written
  anyway: Navidrome then makes a new song, as before, and Releasomat links it on its next refresh.
- **If writing the tags fails** in step 3, the file goes back into the inbox, unchanged (same time
  and size, so the inbox list and the owner's values are still there), and the import is listed
  as failed with its reason, as when writing fails before a normal import.
- **History**: the import entry as always (from where to where, the tag changes, Undo), with one
  line on how it went: listed by Navidrome, scanned, not listed, or not confirmed (with Navidrome's
  answer). It is kept in the entry's `details`.
- **Undo** is unchanged: the tags come back from the snapshot, then the file moves back into the
  inbox.

## Not chosen
- **Two steps for every import**: only adopted files have a Navidrome song worth keeping (a new
  inbox file has none), and the wait would slow every import down.
- **Two steps only when tags of the persistent ID change**: the PID is a setting on the owner's
  Navidrome, so Tagwerk can't know which tags count. One scan per import is cheap.
- **Navidrome's own API** (`/api/song`, as Releasomat uses it) to see the real path: its login
  sends the password itself.
- **Undo in two steps** (tags back in place, scan, then move): not needed. Navidrome also finds a
  missing song by its path, so a file imported again into the same place gets its song back (see
  Consequences).

## Consequences
- Tried end to end against a dev Navidrome 0.64.2 (test files only): two downloads in a playlist,
  starred, rated and played, adopted, given a new title and album in the inbox and imported together
  with an ordinary inbox track. Both kept their song IDs, stars, rating and play counts, came back
  in the playlist with their new titles, and no missing song was left. One scan for both; the import
  took about 2 seconds longer.
- With Releasomat's part (its ADR 0010: the old song stays in the playlist while the file waits in
  the inbox), an adopted track stays the same song everywhere: Releasomat's playlists and snapshots,
  the owner's own playlists, plays, stars and rating, and no second song in Navidrome.
- An import with adopted tracks takes one Navidrome scan longer (seconds; at most 3 minutes while
  Navidrome is busy). The progress line says "Waiting for Navidrome's scan".
- Navidrome sees each adopted file twice: first with Releasomat's tags, a moment later with the new
  ones.
- Needs `ND_SCANNER_PURGEMISSING` = `never`, Navidrome's default: otherwise Navidrome deletes the
  missing song while its file waits in the inbox.
- If Tagwerk is stopped during the wait, the file stays in the library with Releasomat's tags and
  without a History entry; the values typed in the inbox go with the inbox list. The next library
  scan reads it in. (Recording the move before the wait would allow an undo, but not keep the typed
  values either; the wait is seconds, at most 3 minutes, so this stays as it is.)
- The import writes the values the track had when it started: a value typed for that track on its
  page while the import waits for Navidrome isn't written.
- Navidrome also knows a missing song by its **path**: a file that turns up where a missing song's
  file was gets that song back, whatever its tags. So undoing such an import and importing it again
  into the same place keeps the song (tried on the dev Navidrome 0.64.2). The other way round, if
  Navidrome still has a missing song of an earlier file at exactly the new place, the adopted file
  gets that song instead of its own; Releasomat then links it on its next refresh.
- **Replace** (a better copy, [ADR 0037](0037-better-copies.md)) with an adopted file keeps the song
  of the library copy, not the download's; Releasomat links the library copy, as before.

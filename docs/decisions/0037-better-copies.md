# 0037: Better copies: an inbox file that sounds better replaces its library copy
Date: 2026-10-12 · Status: Accepted

## Context
DJs often get a track twice: first as a 192 kbps promo or a rip, later as a 320 kbps or lossless purchase. The inbox already spotted such files as likely copies of a library track ([ADR 0011](0011-inbox-duplicates-and-trash.md)), but the only choices were "import anyway" (a second copy for the Duplicates page) or "move the inbox file to the trash" (keep the poorer sound). The owner wants the better-sounding file to take the library copy's place. This is about **audio quality**, not tags: the library copy usually has the better, hand-checked tags.

## Decision
- **Detecting.** An inbox track is a *better copy* when it is a likely copy of library tracks (same MusicBrainz recording, or same artist and title with about the same length; never the identical file) and sounds **clearly** better than every one of them:
  - lossless (FLAC, WAV, AIFF) instead of lossy;
  - lossless against lossless: a higher bit depth or sample rate, and neither lower (24 bit/44.1 kHz against 16 bit/48 kHz is no clear win, and neither counts when a value is unknown);
  - lossy against lossy: at least 1.2× the bitrate (192 → 256, 256 → 320 count; 320 against a 300 kbps VBR file doesn't). The codec isn't weighed: a bitrate is a bitrate.
  - Never lossy over lossless.
  The copy it replaces is the matching copy with the best sound, then the most tags: the one the Duplicates page would keep. Other copies stay for the Duplicates page.
- **Shown in the Inbox**: a **Better sound** badge and tab, and on the track's page a box comparing both copies, the new path, the tags that will be written and a **Replace library copy** button (with a confirmation). Several can be replaced at once from the tab.
- **What replacing does** (a write job, like an import):
  1. The library copy's tags are written into the inbox file, with a snapshot. The library is the owner's master; fields the library copy lacks get the values an import would write. The cover is the library copy's (if it has one). ReplayGain isn't copied: it belongs to the old audio, so the new file keeps its own and the loudness is measured again.
  2. The new file takes the old one's **folder and name with its own extension** (`Artist - Title.mp3` → `Artist - Title.flac`). This keeps the owner's filename choice; the only change is the extension the format needs.
  3. The old file goes to the **library trash** ([ADR 0023](0023-library-trash.md)), restorable until the owner empties it. Then the new file is copied in, verified and removed from the inbox. If anything fails, the old file comes back and the inbox file keeps its tags.
  4. The track keeps its **database row**: added date, history, final mark (now protecting the new file) and secret mark stay. BPM and key from the inbox file's analysis come along.
  5. Like Convert, it waits until Navidrome has scanned the old file's current tags, and blocks when the library copy has pending changes.
- **Undo** (History) moves the new file back into the inbox with its old tags and restores the old file from the trash into the same row. It is refused, with nothing touched, when the trash was emptied or the old file was restored by hand.
- **Automatic replacing** is an extra switch in Settings → Import (off by default), independent of automatic imports. When on, the regular inbox check replaces library copies on its own, but only for files unchanged for 2 minutes and matches that don't rest on guesses (artist and title from the file, the owner or sure suggestions). A notification topic *Better copies replaced* (off by default) reports them.
- **One rule for "lossless"**: FLAC, WAV and AIFF, as in Statistics. The Duplicates page used the bit depth to spot ALAC in `.m4a` files, but AAC files report 16 bit too, so AAC used to rank above a 320 kbps MP3. It now uses the same ranking as better copies (lossy files by bitrate, not sample rate).

## Consequences
- A second way for library files to reach the library trash besides the Duplicates page: the owner's **Replace** (or the owner's switch for automatic replacing). Tagwerk still never removes a library file for good on its own.
- ALAC files in `.m4a` count as lossy: an ALAC copy is never suggested over an MP3, and a FLAC is suggested over an ALAC library copy. Telling ALAC apart would need the codec stored per file.
- Fake lossless files (an MP3 re-encoded as FLAC) look better than they are. Spotting them needs a spectrum analysis; until then the comparison trusts the format.
- A 96 kHz or 24-bit file may not play on older CDJs. Getting files onto the decks is out of scope ([roadmap](../roadmap.md)); the owner decides per track.
- Navidrome sees a new file (new extension). As with Convert, the new file has the old one's tags and Navidrome has scanned the old file first, which gives it the best chance to keep play counts and ratings.

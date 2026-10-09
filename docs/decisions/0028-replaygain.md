# 0028: ReplayGain fields, read and written in every format
Date: 2026-10-09 · Status: Accepted

## Context
Navidrome evens out playback volume with ReplayGain tags. Tagwerk read only the track gain, and not at all in Opus files, which keep gains in their own fields. The owner wants to edit ReplayGain and later measure it from the audio ([issue #39](https://github.com/dooziedan/tagwerk/issues/39)). This first part covers reading and editing; measuring follows.

## Decision
- **Four fields**: track gain, track peak, album gain, album peak (`replaygain_*` on the track row; three new columns, `SCAN_VERSION` 6 re-reads every track once).
- **Values as taggers write them**: gains in dB relative to −18 LUFS, written as `-6.20 dB` (two decimals); peaks as linear amplitude, written as `0.988525` (six decimals, 1.0 = full scale; true peaks may be above 1). The form accepts `-6.2`, `-6,2 dB` and the like.
- **Where they go**: ID3 `TXXX:REPLAYGAIN_*` (MP3, WAV, AIFF), Vorbis comments `REPLAYGAIN_*` (FLAC, OGG), MP4 freeform `----:com.apple.iTunes:replaygain_*` (M4A). A file that already spells the name differently keeps its spelling.
- **Opus follows RFC 7845**: gains in `R128_TRACK_GAIN` / `R128_ALBUM_GAIN`, whole numbers in 1/256 dB relative to −23 LUFS (ReplayGain gain − 5 dB, × 256). Writing a gain replaces a `REPLAYGAIN_*` gain some taggers add to Opus files; reading prefers the R128 field. Opus has **no peak fields**: the writer refuses them, staging skips them for Opus tracks (`writer.supports`), and the edit page leaves them out.
- **Their own section on the edit page** (single and batch edit), separate from the main tags: like the IDs, ReplayGain isn't part of the inbox review, the import or the final check.
- The edit form stages only the fields it sends, so a field the form doesn't show stays as it is.

## Consequences
- The gain of an Opus file can only be stored to 1/256 dB; it reads back the same at two decimals.
- ID3 `RVA2` frames (an older volume format) are neither read nor changed.
- Measuring from the audio can stage these four fields like BPM and key ([issue #39](https://github.com/dooziedan/tagwerk/issues/39), part 2).

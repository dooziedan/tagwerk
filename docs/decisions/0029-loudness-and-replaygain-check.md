# 0029: Loudness from the audio, and checking ReplayGain against it
Date: 2026-10-09 · Status: Accepted

## Context
Part 2 of [issue #39](https://github.com/dooziedan/tagwerk/issues/39). The owner wants every track at the same listening level. Some tracks already have ReplayGain, but it can't be trusted: older taggers used ReplayGain 1 (reference 89 dB, about −14 LUFS), newer ones ReplayGain 2.0 (−18 LUFS), and tags get copied between releases and edits. A library mixing them is levelled unevenly although every track "has ReplayGain".

ReplayGain is a tag, not a change to the sound: only players that read it apply it. The owner listens in Navidrome (reads it) and plays sets on a CDJ-2000NXS and an XDJ-RX3 from rekordbox USB exports. Those read rekordbox's export database, not ReplayGain tags, and as far as we could find, rekordbox's Auto Gain isn't applied by players from a USB export either. So ReplayGain levels Navidrome; for the decks, Tagwerk can only show which tracks are louder or quieter. Changing the sound itself (lossless gain for AIFF/WAV/FLAC) is a separate, later release.

## Decision
- **Measured with ffmpeg's EBU R128 meter** (`ebur128=peak=true`, already in the image): integrated loudness in LUFS and true peak. About 1.6 s for a 4½-minute track; `loudnorm` gives the same values and took 9 s. Run in the analysis job (one more ffmpeg pass per library track, `nice -n 10`, the same worker count), kept in `libraryloudness` and redone only for a newer method (`LOUDNESS_VERSION`) or a different length, like the BPM/key analysis. Library tracks only: inbox tracks are measured after import.
- **The gain a track should have**: −18 LUFS minus its loudness (ReplayGain 2.0), with the true peak as the peak (stricter than the sample peak, so clipping protection errs on the safe side).
- **Checking**: within 0.5 dB counts as matching (meters differ by a tenth or two). A tag 3-5 dB higher than measured is named an *old ReplayGain 1 value*; other differences "don't match the audio"; a right gain without a peak gets the peak. The page lists them worst first; tracks whose fix already waits on Changes and final tracks aren't counted.
- **Fixing is the owner's choice**: ticked tracks (or all) become pending changes (source "From the audio") with track gain and peak; nothing is staged on its own, unlike sure BPM and key for empty fields, because hundreds of tracks would change at once. Album gain is left alone: DJ tracks are mostly singles, and Navidrome should use its *track* mode.
- Home shows the number of tracks to fix; the track page shows the loudness.

## Consequences
- A big library takes a while to measure the first time (about 40 minutes of one core for 1,500 tracks, shared between the workers).
- ffmpeg prints the loudness with one decimal, so gains are exact to 0.1 dB, far finer than anyone hears.
- The loudness spread on the page (and the track page) helps to set the trim before a set; making the decks themselves even needs the later sound-changing release.

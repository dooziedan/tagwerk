# 0017: BPM and key from the audio
Date: 2026-10-06 · Status: Accepted

## Context
Many tracks arrive without BPM or key, or with wrong ones: drum & bass tagged at half tempo (87 instead of 174), keys from different tools. The owner is a DJ whose biggest genre is drum & bass. Tagwerk should measure BPM and key itself, inside the Docker image, and combine that with what it already knows (filename, online sources, genre). The owner prefers precision over speed.

## Decision
- **Library: Essentia** (pinned `essentia==2.1b6.dev1438`, AGPL-3.0, needs `libatomic1` in the image). librosa has no key detection and a coarse tempo; aubio and madmom have no packages for current Python. The image grows by about 150 MB.
- **The engine** (`app/audio_analysis.py`) only reads: ffmpeg decodes the first 15 minutes to mono 44.1 kHz; shorter than 10 seconds or silent is an error, not a guess.
- **BPM**: three methods (RhythmExtractor2013 multifeature and degara, Percival) vote. Each answer also counts for double, half and 3:2 tempo (a triplet feel made two methods hear 115.6 for a 174 track), and the tempo explaining most answers wins. The methods only know steps of about 0.7 BPM near 87 (172, 174 and 176 all came out as "86.9"), so the winner is **measured precisely**: the track's onset strength is compared with itself 1-64 beats later at tempos 0.05 BPM apart. On 12 reference tracks this was within 0.02 % of the true tempo; the one "miss" (Beatport's 176) turned out to be a rounded half-time value (88 x 2), the audio says 175.
- **Key**: `KeyExtractor` with the `edmm` profile (made for electronic music) and **8192-sample frames**: sub-bass notes are only 2-3 Hz apart, and Essentia's default 4096 blurs them (both drum & bass references wrong with the default, both right with 8192, no change for house). Sure only when the result holds with 16384-sample frames and another profile hears the same notes (Camelot number); minor or major is `edmm`'s call. On the references every "sure" key was right; both wrong ones were marked "check".
- **Running**: one track at a time, each in **its own process with `nice -n 10`** (`app/analysis.py`): pages stay fast, the GIL doesn't matter, and a crash can't stop the server. Inbox tracks are analysed after every inbox check; library tracks on demand (track page, ticked tracks, all matching the list's filters), inbox first. Results are kept (`inboxanalysis`, `libraryanalysis`); writing tags doesn't change the sound, so a result is only redone when the method version or the track length changes. On import the inbox result moves to the library track.
- **Deciding** (`analysis.decide`): the audio's answer and its alternatives are combined with the genre (a tempo range per genre, e.g. drum & bass 160-185, settles 87 or 174), the filename, online sources (Deezer's BPM) and the tag. A hint picks between what the audio allows and makes it sure; a hint the audio contradicts makes it "check". Rounded half-time hints are allowed 1.5 % (88 x 2 for 175).
- **Using it**:
  - Empty fields: sure values become **pending changes** (library) or **suggestions** (inbox, replacing the filename's and online sources' BPM and key, which the decision already took into account). Automatic imports wait until a track is analysed.
  - Existing tags that differ: **only flagged** (track list filters and dashboard: BPM probably half or double time, BPM differs, key differs), with a "Use" button on the track page. Only sure decisions are compared.

## Consequences
- 5-10 seconds of one CPU core per track; a big library takes hours, in the background. Up to about 750 MB of memory while one long mix is analysed.
- The reference set is small (12 tracks, 5 drum & bass). The flags on the owner's library will show the real accuracy; the method has a version number, so improvements re-analyse old results.
- Essentia is a beta build; the pin keeps results stable until it is deliberately updated.

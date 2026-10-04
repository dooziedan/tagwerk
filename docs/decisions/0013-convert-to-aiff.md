# 0013: Converting to AIFF, with originals kept aside
Date: 2026-10-04 · Status: Accepted

## Context
The owner wants lossless tracks as AIFF (one format for DJ use, tags and cover art stored like MP3s). Converting must keep every tag and the cover, put the AIFF where the library layout says, and keep the original for the owner to decide about later.

## Decision
- **ffmpeg (with ffprobe) is part of the Docker image.** It is the most widely used audio tool, with a big community, and it reads every lossless format the library has (FLAC, PCM in WAV, ALAC). The Debian package adds about 457 MB to the image, roughly doubling it; the owner accepted that for this feature. A smaller library (soundfile/libsndfile) was tried and works for FLAC and WAV, but can't read ALAC and was set aside in favour of the standard tool.
- **Only lossless sources** are converted, judged by what ffprobe reports for the audio stream: FLAC, uncompressed PCM in WAV, and ALAC in `.m4a`. Lossy audio (MP3, AAC, OGG, Opus, and compressed audio hidden in a WAV such as MP3 or ADPCM) is skipped and listed as skipped: an AIFF of an MP3 is ~8× bigger and sounds the same. AIFF files are skipped too.
- Sample rate and bit depth stay as they are (16 → 16, 24 → 24, float → float); samples are copied bit-exact.
- **All tags** are carried over as ID3v2.4 inside the AIFF: from Vorbis/MP4 with MusicBrainz Picard's mapping, unknown fields as TXXX frames under their own name, ID3 from WAV copied unchanged, RIFF INFO mapped. All pictures keep their type. `app/tagcopy.py` builds the frames; `app/writer.py` writes them (it stays the only code that writes tags).
- **Verified before anything moves**: the AIFF is read back; its length (±0.1 s), every field Tagwerk reads and the cover must match the source. Otherwise it is removed and the track stays as it was.
- The AIFF goes into the folder chosen by **Settings → Import folders** (same filename, `.aiff`); a `.lrc` lyrics file goes along.
- The **original** moves to a separate container path, **`/originals`** (Unraid template: *Original Files*), under its library path; copy → verify → delete, because it is usually another share. The owner decides what happens to them; Tagwerk never deletes them.
- The track keeps its database row, so a **final** track stays final.
- Before converting, Navidrome must have scanned the file's current tags (as for renaming, ADR 0012), so it can connect the AIFF to the track's play counts and ratings.
- Recorded in the history. **Undo** moves the original back and removes the AIFF. This is the only case where Tagwerk deletes a library file: the AIFF it created itself, only if it is unchanged since converting (file time).

## Consequences
- The image grows by the ffmpeg package (~457 MB).
- Converting needs the *Original Files* path set up; without it, the page explains how.
- Big batches take a while (converting plus copying originals to another share) and run as a background job.

"""Converting library tracks to AIFF, with every tag and picture (ADR 0013).

Per track:
1. **Check**: only lossless sources (FLAC, WAV with uncompressed audio, ALAC in .m4a, as
   ffprobe reports them); no pending changes; the file is as last scanned; the new AIFF and
   the place for the original are free; Navidrome has scanned the file's current tags (so it
   can connect the new file to play counts and ratings).
2. **Convert** with ffmpeg: same sample rate and bit depth, samples unchanged, written next
   to the target under a temporary name.
3. **Tags**: all tags and pictures, translated to ID3 (app/tagcopy.py), written by app/writer.py.
4. **Verify**: the new file is read back; length, every field Tagwerk knows and the cover must
   match the source, else the new file is removed and nothing else happens.
5. **Move**: the AIFF goes into the library folder chosen by the import folder layout (same
   filename, new extension; a .lrc lyrics file goes along). The original is copied into
   ORIGINALS_DIR under its library path, the copy verified, then removed from the library.
6. The track keeps its database row (and so its final mark); undo brings the original back and
   removes the AIFF Tagwerk created.
"""

import contextlib
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import genres, naming, navidrome, preferences, tagcopy, writer
from app.changes import WriteProgress
from app.config import Settings
from app.importer import move_file
from app.models import ChangeEntry, ChangeSet, FinalTrack, PendingChange, Track
from app.scanner import store_file
from app.tags import _riff_info_chunks, read_file

log = logging.getLogger(__name__)

TIMEOUT = 900  # seconds for one ffmpeg run (a long DJ mix as 24-bit WAV takes a while)
# Lossless audio as ffprobe names it → the AIFF's sample format (8-bit becomes 16-bit; float
# stays float). Anything else (MP3, AAC, ADPCM in a WAV, …) is lossy and not converted.
_PCM = {"pcm_u8": "pcm_s16be", "pcm_s8": "pcm_s16be", "pcm_s16le": "pcm_s16be",
        "pcm_s16be": "pcm_s16be", "pcm_s24le": "pcm_s24be", "pcm_s24be": "pcm_s24be",
        "pcm_s32le": "pcm_s32be", "pcm_s32be": "pcm_s32be", "pcm_f32le": "pcm_f32be",
        "pcm_f64le": "pcm_f64be"}  # fmt: skip
_BY_BITS = {"flac", "alac"}  # compressed but lossless: the bit depth picks the sample format
LENGTH_TOLERANCE = 0.1  # seconds the AIFF may differ from the source
# Fields compared after converting: everything Tagwerk reads must come out the same.
VERIFY = ("title", "artist", "album", "albumartist", "tracknumber", "tracktotal", "discnumber",
          "disctotal", "date", "genre", "key", "comment", "label", "catalognumber", "mb_trackid",
          "mb_albumid", "mb_artistid", "mb_albumartistid", "has_cover", "has_lyrics",
          "replaygain_track_gain")  # fmt: skip


class ConvertError(Exception):
    """A track can't be converted (the message says why)."""


def available(settings: Settings) -> str | None:
    """Why converting isn't possible at all right now, or None."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        return "ffmpeg is missing in this installation."
    if not settings.originals_dir.is_dir():
        return (
            f"The folder for original files ({settings.originals_dir}) isn't set up. On Unraid, "
            "fill in Original Files in the Tagwerk container settings."
        )
    return None


@dataclass
class Plan:
    track: Track
    target: str | None  # the AIFF's library path, relative to MUSIC_DIR
    skip: str | None = None  # why this track isn't converted

    @property
    def original(self) -> str:
        """Where the original goes, relative to ORIGINALS_DIR (its library path)."""
        return self.track.path


def plan(session: Session, settings: Settings, tracks: list[Track]) -> list[Plan]:
    """What converting these tracks would do; tracks that can't be converted say why."""
    prefs = preferences.load(session)
    genre_map = genres.from_text(prefs.genre_map)
    existing = naming.existing_folders(settings.music_dir)
    pending = set(
        session.exec(
            select(PendingChange.track_id).where(
                col(PendingChange.track_id).in_([t.id for t in tracks])
            )
        )
    )
    targets: set[str] = set()
    result = []
    for track in tracks:
        values = naming.values_for(
            {f: writer.current_value(track, f) for f in writer.EDITABLE},
            genre_map,
            prefs.key_notation,
        )
        folder = naming.folder(
            prefs.folder_layout, prefs.folder_pattern, values, prefs.genre_folders, existing
        )
        target = f"{folder}/{PurePosixPath(track.path).stem}.aiff"
        item = Plan(track, target, _skip_reason(settings, track, target, targets, pending))
        if not item.skip:
            targets.add(target.lower())
        result.append(item)
    return result


def _skip_reason(settings, track: Track, target: str, targets: set, pending: set) -> str | None:
    if track.error:
        return "the file can't be read"
    if track.format == "aiff":
        return "already AIFF"
    path = settings.music_dir / track.path
    if _audio_codec(path) is None:
        return f"lossy ({_codec_name(path, track)}): only lossless files are converted"
    if track.id in pending:
        return "has pending changes: apply or discard them first"
    if (settings.music_dir / target).exists() or target.lower() in targets:
        return f"{target} already exists"
    if (settings.originals_dir / track.path).exists():
        return "a file with this path is already in the original files folder"
    return None


def _probe(path: Path) -> dict:
    """The first audio stream as ffprobe sees it ({} if it can't be read)."""
    entries = "stream=codec_name,bits_per_raw_sample,sample_fmt"
    command = ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", entries,
               "-of", "json", str(path)]  # fmt: skip
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
        return (json.loads(done.stdout or "{}").get("streams") or [{}])[0]
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def _audio_codec(path: Path) -> str | None:
    """The AIFF sample format for a lossless file, or None when the audio is lossy."""
    stream = _probe(path)
    codec = stream.get("codec_name", "")
    if codec in _PCM:
        return _PCM[codec]
    if codec in _BY_BITS:
        bits = int(stream.get("bits_per_raw_sample") or 16)
        return "pcm_s16be" if bits <= 16 else "pcm_s24be" if bits <= 24 else "pcm_s32be"
    return None


def _codec_name(path: Path, track: Track) -> str:
    """For the skip reason: "MP3", "AAC", or the codec inside a WAV like "ADPCM_IMA_WAV"."""
    codec = _probe(path).get("codec_name") or track.format
    return {"aac": "AAC", "mp3": "MP3", "vorbis": "OGG", "opus": "Opus"}.get(codec, codec.upper())


# --- Converting (a background job) ----------------------------------------------------------


def convert(engine: Engine, settings: Settings, track_ids: list[int], progress: WriteProgress):
    """Convert the given tracks; tracks that can't be converted are listed as failed."""
    reason = available(settings)
    if reason:
        raise ConvertError(reason)
    with Session(engine) as session:
        tracks = list(
            session.exec(select(Track).where(col(Track.id).in_(track_ids)).order_by(Track.path))
        )
        items = plan(session, settings, tracks)
        progress.total = len(items)
        changeset = ChangeSet(kind="convert", tracks=len(items), fields="Converted to AIFF")
        session.add(changeset)
        session.commit()
        progress.changeset_id = changeset.id
        for item in items:
            track = item.track
            old_path, old_format = track.path, track.format
            progress.current = old_path
            entry = ChangeEntry(
                changeset_id=changeset.id,
                track_id=track.id,
                path=item.target,
                changes=json.dumps({"format": [old_format, "aiff"]}),
                moved_from=old_path,
            )
            try:
                if item.skip:
                    raise ConvertError(item.skip)
                _convert_one(session, settings, item, entry)
                progress.written += 1
                changeset.written += 1
            except Exception as exc:
                log.warning("Could not convert %s: %s", old_path, exc)
                session.rollback()
                entry.path, entry.moved_from = old_path, None  # nothing changed
                entry.error = str(exc)[:500]
                progress.failed += 1
                changeset.failed += 1
                progress.errors.append(f"{old_path}: {entry.error}")
            session.add(entry)
            session.add(changeset)
            session.commit()
            progress.processed += 1
    progress.current = ""
    navidrome.rescan_after_write(settings, progress.written)


def _convert_one(session: Session, settings: Settings, item: Plan, entry: ChangeEntry) -> None:
    track = item.track
    source = settings.music_dir / track.path
    target = settings.music_dir / item.target
    original = settings.originals_dir / item.original
    stat = source.stat()
    if stat.st_mtime != track.mtime or stat.st_size != track.size:
        raise ConvertError("the file changed since the last scan; scan again")
    ready = navidrome.scanned_since(settings, stat.st_mtime)
    if not ready.ok:
        raise ConvertError(f"Not converted: {ready.message}")

    new_folder = not target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.stem}.tagwerk-part.aiff")
    try:
        _ffmpeg(source, part)
        riff = _riff_info_chunks(source) if track.format == "wav" else None
        writer.tag_converted(part, tagcopy.id3_frames(source, riff))
        _verify(source, part)
        if target.exists():
            raise ConvertError(f"{item.target} appeared in the meantime; nothing was replaced")
        part.rename(target)
        move_file(source, original)  # copy → verify → delete, into ORIGINALS_DIR
    except Exception:
        part.unlink(missing_ok=True)  # keep things as they were: the original stays
        target.unlink(missing_ok=True)
        if new_folder:
            with contextlib.suppress(OSError):  # only removes an empty folder
                target.parent.rmdir()
        raise
    lyrics = source.with_suffix(".lrc")
    has_lrc = False
    if lyrics.exists() and not target.with_suffix(".lrc").exists():
        lyrics.rename(target.with_suffix(".lrc"))
        has_lrc = True

    new_stat = target.stat()
    store_file(session, target, item.target, new_stat, has_lrc, track.id)
    final = session.get(FinalTrack, track.id)
    if final:  # the mark stays; the new file is what it now protects
        final.mtime = new_stat.st_mtime
        session.add(final)
    entry.mtime_after = new_stat.st_mtime
    log.info("Converted %s to %s", track.path, item.target)


def _ffmpeg(source: Path, part: Path) -> None:
    """Decode the source and write its samples unchanged into an AIFF (no tags yet)."""
    codec = _audio_codec(source)
    if codec is None:
        raise ConvertError("the audio is lossy")
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-map", "0:a:0", "-map_metadata", "-1",
        "-c:a", codec, "-f", "aiff", str(part),
    ]  # fmt: skip
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ConvertError("converting took too long") from None
    if done.returncode != 0:
        raise ConvertError(f"ffmpeg: {done.stderr.strip()[-300:] or 'failed'}")


def _verify(source: Path, converted: Path) -> None:
    """The AIFF must have the same length and the same tags as the source."""
    before = read_file(source)
    try:
        after = read_file(converted)
    except Exception as exc:
        raise ConvertError(f"the converted file can't be read back ({exc})") from None
    if after.format != "aiff":
        raise ConvertError("the converted file isn't an AIFF")
    if before.duration and abs((after.duration or 0) - before.duration) > LENGTH_TOLERANCE:
        raise ConvertError(
            f"length differs ({after.duration:.2f}s instead of {before.duration:.2f}s)"
        )
    different = [f for f in VERIFY if getattr(before, f) != getattr(after, f)]
    if before.bpm is not None and round(before.bpm) != round(after.bpm or 0):
        different.append("bpm")
    if different:
        raise ConvertError("tags differ after converting: " + ", ".join(different))


# --- Undo -----------------------------------------------------------------------------------


def undo(session: Session, entry: ChangeEntry, settings: Settings) -> None:
    """The original comes back from ORIGINALS_DIR; the AIFF Tagwerk created is removed."""
    converted = settings.music_dir / entry.path
    original = settings.originals_dir / entry.moved_from
    back = settings.music_dir / entry.moved_from
    if not original.exists():
        raise ConvertError("the original is no longer in the original files folder")
    if back.exists():
        raise ConvertError(f"{entry.moved_from} exists again in the library")
    move_file(original, back)
    lyrics = converted.with_suffix(".lrc")
    has_lrc = False
    if lyrics.exists():
        lyrics.rename(back.with_suffix(".lrc"))
        has_lrc = True
    converted.unlink()  # only ever the AIFF this conversion created (checked by its file time)
    track = session.get(Track, entry.track_id) if entry.track_id else None
    if track:
        stat = back.stat()
        store_file(session, back, entry.moved_from, stat, has_lrc, track.id)
        final = session.get(FinalTrack, track.id)
        if final:
            final.mtime = stat.st_mtime
            session.add(final)

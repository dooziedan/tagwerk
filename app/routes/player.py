"""Listening to tracks: the audio for the play bar (app/static/player.js).

- ``/tracks/{id}/audio`` and ``/inbox/{id}/audio``: the file itself, with range requests, so
  the browser can jump to any point. Read-only.
- ``…/audio.mp3?start=SECONDS``: for formats browsers can't play (AIFF everywhere, ALAC in most
  browsers), ffmpeg converts on the fly to MP3, starting at ``start``; jumping reloads it there.
"""

import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.config import SettingsDep
from app.db import SessionDep
from app.models import InboxTrack, Track

router = APIRouter()

MIME = {
    "mp3": "audio/mpeg",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "aiff": "audio/aiff",
    "m4a": "audio/mp4",
    "ogg": "audio/ogg",
    "opus": "audio/ogg; codecs=opus",
}
CHUNK = 64 * 1024


@router.get("/tracks/{track_id}/audio", include_in_schema=False)
def track_audio(track_id: int, session: SessionDep, settings: SettingsDep):
    track = session.get(Track, track_id)
    return _file(settings.music_dir, track)


@router.get("/tracks/{track_id}/audio.mp3", include_in_schema=False)
def track_audio_mp3(track_id: int, session: SessionDep, settings: SettingsDep, start: float = 0):
    return _mp3(settings.music_dir, session.get(Track, track_id), start)


@router.get("/inbox/{track_id}/audio", include_in_schema=False)
def inbox_audio(track_id: int, session: SessionDep, settings: SettingsDep):
    return _file(settings.import_dir, session.get(InboxTrack, track_id))


@router.get("/inbox/{track_id}/audio.mp3", include_in_schema=False)
def inbox_audio_mp3(track_id: int, session: SessionDep, settings: SettingsDep, start: float = 0):
    return _mp3(settings.import_dir, session.get(InboxTrack, track_id), start)


def _path(root: Path, track) -> Path:
    """The track's file; never anything outside its folder."""
    if track is None:
        raise HTTPException(404)
    base = root.resolve()
    path = (base / track.path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(404)
    return path


def _file(root: Path, track) -> FileResponse:
    path = _path(root, track)
    return FileResponse(path, media_type=MIME.get(track.format, "application/octet-stream"))


def _mp3(root: Path, track, start: float) -> StreamingResponse:
    path = _path(root, track)
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(start, 0):.2f}", "-i", str(path), "-map", "0:a:0", "-vn",
        "-c:a", "libmp3lame", "-b:a", "320k", "-f", "mp3", "pipe:1",
    ]  # fmt: skip

    def stream():
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while chunk := process.stdout.read(CHUNK):
                yield chunk
        finally:  # the listener stopped or jumped elsewhere: end ffmpeg too
            process.kill()
            process.wait()

    return StreamingResponse(stream(), media_type="audio/mpeg")

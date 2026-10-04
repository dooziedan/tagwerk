"""Generate the tiny audio files used by the tests (half a second of silence, with known tags).

The generated files are committed; run this again only to change or add fixtures:

    .venv/bin/python tests/fixtures/generate.py

Needs ffmpeg for the audio itself. Tags are written with mutagen, the way taggers like
MusicBrainz Picard write them.
"""

import base64
import subprocess
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TALB,
    TBPM,
    TCON,
    TDRC,
    TIT2,
    TKEY,
    TPE1,
    TPE2,
    TPOS,
    TPUB,
    TRCK,
    TXXX,
    UFID,
    USLT,
)
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

HERE = Path(__file__).parent

# A valid 1x1 PNG, used as cover art.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

TAGS = {
    "title": "Silent Track",
    "artist": ["Artist One", "Artist Two"],
    "album": "Fixture Album",
    "albumartist": "Fixture Artist",
    "track": (3, 12),
    "disc": (1, 2),
    "date": "2021-05-14",
    "genre": "Electronic",
    "mb_trackid": "11111111-1111-4111-8111-111111111111",
    "mb_albumid": "22222222-2222-4222-8222-222222222222",
    "mb_artistid": "33333333-3333-4333-8333-333333333333",
    "mb_albumartistid": "44444444-4444-4444-8444-444444444444",
    # DJ fields
    "bpm": "126",
    "key": "Am",
    "comment": "Whatsapp Unreleased",
    "label": "Fixture Records",
    "catalognumber": "FIX001",
    "replaygain": "-6.20 dB",
    "lyrics": "La la la",
}


def picture() -> Picture:
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/png", PNG
    return pic


def silence(name: str, *ffmpeg_args: str) -> Path:
    path = HERE / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "0.5", *ffmpeg_args, str(path)],
        check=True,
    )  # fmt: skip
    return path


def tag_id3(tags: ID3) -> ID3:
    t = TAGS
    tags.add(TIT2(encoding=3, text=t["title"]))
    tags.add(TPE1(encoding=3, text=t["artist"]))
    tags.add(TALB(encoding=3, text=t["album"]))
    tags.add(TPE2(encoding=3, text=t["albumartist"]))
    tags.add(TRCK(encoding=3, text="{}/{}".format(*t["track"])))
    tags.add(TPOS(encoding=3, text="{}/{}".format(*t["disc"])))
    tags.add(TDRC(encoding=3, text=t["date"]))
    tags.add(TCON(encoding=3, text=t["genre"]))
    tags.add(TXXX(encoding=3, desc="MusicBrainz Album Id", text=t["mb_albumid"]))
    tags.add(TXXX(encoding=3, desc="MusicBrainz Artist Id", text=t["mb_artistid"]))
    tags.add(TXXX(encoding=3, desc="MusicBrainz Album Artist Id", text=t["mb_albumartistid"]))
    tags.add(UFID(owner="http://musicbrainz.org", data=t["mb_trackid"].encode()))
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="Cover", data=PNG))
    tags.add(TBPM(encoding=3, text=t["bpm"]))
    tags.add(TKEY(encoding=3, text=t["key"]))
    tags.add(COMM(encoding=3, lang="eng", desc="", text=t["comment"]))
    tags.add(COMM(encoding=3, lang="eng", desc="iTunNORM", text="00000A 00000B"))  # hidden
    tags.add(TPUB(encoding=3, text=t["label"]))
    tags.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=t["catalognumber"]))
    tags.add(TXXX(encoding=3, desc="REPLAYGAIN_TRACK_GAIN", text=t["replaygain"]))
    tags.add(USLT(encoding=3, lang="eng", desc="", text=t["lyrics"]))
    return tags


def make_id3_files() -> None:
    mp3 = silence("tagged.mp3", "-c:a", "libmp3lame", "-b:a", "32k")
    tags = tag_id3(ID3())
    tags.save(mp3)

    for name, ext in (("tagged.wav", "wav"), ("tagged.aiff", "aiff")):
        path = silence(name, "-c:a", "pcm_s16le" if ext == "wav" else "pcm_s16be")
        audio = (WAVE if ext == "wav" else AIFF)(path)
        audio.add_tags()
        tag_id3(audio.tags)
        audio.save()


def tag_vorbis(audio) -> None:
    """Vorbis comments, shared by FLAC, OGG and Opus."""
    t = TAGS
    audio["title"] = t["title"]
    audio["artist"] = t["artist"]
    audio["album"] = t["album"]
    audio["albumartist"] = t["albumartist"]
    audio["tracknumber"] = str(t["track"][0])
    audio["tracktotal"] = str(t["track"][1])
    audio["discnumber"] = str(t["disc"][0])
    audio["disctotal"] = str(t["disc"][1])
    audio["date"] = t["date"]
    audio["genre"] = t["genre"]
    for key in ("trackid", "albumid", "artistid", "albumartistid"):
        audio[f"musicbrainz_{key}"] = t[f"mb_{key}"]
    audio["bpm"] = t["bpm"]
    audio["initialkey"] = t["key"]
    audio["comment"] = t["comment"]
    audio["label"] = t["label"]
    audio["catalognumber"] = t["catalognumber"]
    audio["replaygain_track_gain"] = t["replaygain"]
    audio["lyrics"] = t["lyrics"]


def make_vorbis_files() -> None:
    flac = FLAC(silence("tagged.flac", "-c:a", "flac"))
    tag_vorbis(flac)
    flac.add_picture(picture())
    flac.save()

    # OGG and Opus store cover art as a base64 picture block inside the comments.
    for name, cls, codec in (
        ("tagged.ogg", OggVorbis, "libvorbis"),
        ("tagged.opus", OggOpus, "libopus"),
    ):
        audio = cls(silence(name, "-c:a", codec))
        tag_vorbis(audio)
        audio["metadata_block_picture"] = base64.b64encode(picture().write()).decode()
        audio.save()


def make_m4a() -> None:
    path = silence("tagged.m4a", "-c:a", "aac", "-b:a", "32k")
    audio = MP4(path)
    t = TAGS
    audio["\xa9nam"] = t["title"]
    audio["\xa9ART"] = t["artist"]
    audio["\xa9alb"] = t["album"]
    audio["aART"] = t["albumartist"]
    audio["trkn"] = [t["track"]]
    audio["disk"] = [t["disc"]]
    audio["\xa9day"] = t["date"]
    audio["\xa9gen"] = t["genre"]
    for name, key in (
        ("Track", "mb_trackid"),
        ("Album", "mb_albumid"),
        ("Artist", "mb_artistid"),
        ("Album Artist", "mb_albumartistid"),
    ):
        audio[f"----:com.apple.iTunes:MusicBrainz {name} Id"] = [MP4FreeForm(t[key].encode())]
    audio["covr"] = [MP4Cover(PNG, imageformat=MP4Cover.FORMAT_PNG)]
    audio["tmpo"] = [int(t["bpm"])]
    audio["\xa9cmt"] = t["comment"]
    audio["\xa9lyr"] = t["lyrics"]
    for name, key in (
        ("initialkey", "key"),
        ("LABEL", "label"),
        ("CATALOGNUMBER", "catalognumber"),
        ("replaygain_track_gain", "replaygain"),
    ):
        audio[f"----:com.apple.iTunes:{name}"] = [MP4FreeForm(t[key].encode())]
    audio.save()


def make_special_cases() -> None:
    # WAV with only old-style RIFF INFO tags (ffmpeg writes INFO for WAV metadata).
    silence(
        "riff-info.wav",
        "-c:a", "pcm_s16le",
        "-metadata", "title=Info Title",
        "-metadata", "artist=Info Artist",
        "-metadata", "album=Info Album",
        "-metadata", "date=1999",
        "-metadata", "track=7",
        "-metadata", "comment=Info Comment",
    )  # fmt: skip
    # No tags at all.
    silence("untagged.mp3", "-c:a", "libmp3lame", "-b:a", "32k", "-write_xing", "0",
            "-id3v2_version", "0", "-write_id3v1", "0")  # fmt: skip
    # Discogs IDs in MusicBrainz fields, like some taggers write them.
    path = silence("discogs-ids.flac", "-c:a", "flac")
    audio = FLAC(path)
    audio["title"] = "Wrong IDs"
    audio["musicbrainz_albumid"] = "25124086"
    audio.save()


if __name__ == "__main__":
    make_id3_files()
    make_vorbis_files()
    make_m4a()
    make_special_cases()
    for p in sorted(HERE.glob("*.*")):
        if p.suffix != ".py":
            print(f"{p.name:20} {p.stat().st_size:>6} bytes")

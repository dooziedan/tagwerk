"""Build a made-up music library for screenshots (README, docs). Needs ffmpeg.

The repository is public, so screenshots never show real music: every artist, title, label and
cover here is invented, and the audio is silence (small files, real lengths). It includes what
the pages are about: genres and subgenres, BPM and keys, a few gaps in the tags, copies of a
track for the Duplicates page, and new tracks waiting in the inbox.

    .venv/bin/python scripts/showcase_library.py dev/showcase

Creates <folder>/music, <folder>/import and an empty <folder>/config. Point a Tagwerk container
at them (see docs/development.md), finish the setup and scan.
"""

import random
import subprocess
import sys
from pathlib import Path

from mutagen.aiff import AIFF
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TBPM, TCON, TDRC, TIT2, TKEY, TPE1, TPUB, TRCK, TXXX

ARTISTS = ["Nova Halcyon", "Kite Signal", "Orbit Theory", "Lumen Drift", "Sable Static",
           "Echo Meridian", "Vanta Bloom", "Polar Tides", "Neon Harbour", "Quiet Satellite",
           "Mira Vale", "Tessellate"]  # fmt: skip
WORDS = ["Low Light", "Afterglow", "Night Ferry", "Tidal", "Gravity Well", "Paper Moons",
         "Signal Lost", "Slow Motion", "Undertow", "Cascade", "Static Hearts", "Glasshouse",
         "Northern Line", "Heat Haze", "Parallax", "Small Hours", "Satellite Love", "Ember",
         "Sea Glass", "Lighthouse", "Velvet Hour", "Zero Gravity", "Outer Rim",
         "Halflight"]  # fmt: skip
MIXES = ["", "", "", " (Extended Mix)", " (VIP)", " (Dub)", " (Club Mix)"]
LABELS = ["Starfield Audio", "Low Orbit", "Night Shift Music", "Halo Records", "Tidewater"]
GENRES = {  # genre tag -> (folder, BPM range)
    "Drum & Bass; Liquid": ("Drum & Bass", (172, 176)),
    "Drum & Bass; Neurofunk": ("Drum & Bass", (172, 175)),
    "Drum & Bass": ("Drum & Bass", (170, 176)),
    "House; Deep House": ("House", (120, 124)),
    "House": ("House", (122, 126)),
    "Tech House": ("Tech House", (124, 128)),
    "Techno": ("Techno", (128, 134)),
    "UK Garage": ("UK Garage", (130, 134)),
    "Breaks": ("Breaks", (128, 136)),
}
MINOR = ["Abm", "Ebm", "Bbm", "Fm", "Cm", "Gm", "Dm", "Am", "Em", "Bm", "F#m", "Dbm"]
MAJOR = ["B", "F#", "Db", "Ab", "Eb", "Bb", "F", "C", "G", "D", "A", "E"]
COLOURS = ["0x312e81", "0x4338ca", "0x7c3aed", "0x0ea5e9", "0xf5c542", "0xe11d48", "0x10b981",
           "0xf97316", "0x1e1b4b", "0xa5b4fc"]  # fmt: skip


def silence(path: Path, seconds: float, fmt: str, noise: bool = False) -> None:
    """Silent audio; ``noise``: very quiet noise instead, so a FLAC has a realistic size."""
    codec = {"flac": ["-c:a", "flac"], "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
             "aiff": ["-c:a", "pcm_s16be"]}[fmt]  # fmt: skip
    source = "anoisesrc=r=44100:a=0.002:c=pink" if noise else "anullsrc=r=44100:cl=stereo"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    source, "-ac", "2", "-t", f"{seconds:.1f}", *codec, str(path)],
                   check=True)  # fmt: skip


def cover(rnd: random.Random) -> bytes:
    """An abstract square: a gradient in two or three of the palette's colours."""
    colours = rnd.sample(COLOURS, 3)
    kind = rnd.choice(["linear", "radial", "circular", "spiral"])
    spec = (f"gradients=s=500x500:c0={colours[0]}:c1={colours[1]}:c2={colours[2]}:nb_colors=3"
            f":type={kind}:seed={rnd.randint(1, 10_000)}")  # fmt: skip
    done = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", spec,
                           "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "-"],
                          check=True, capture_output=True)  # fmt: skip
    return done.stdout


def tag(path: Path, t: dict) -> None:
    if path.suffix == ".flac":
        audio = FLAC(path)
        for key, value in t.items():
            if key != "cover" and value is not None:
                audio[{"key": "initialkey", "label": "label"}.get(key, key)] = str(value)
        if t.get("cover"):
            picture = Picture()
            picture.type, picture.mime, picture.data = 3, "image/jpeg", t["cover"]
            audio.add_picture(picture)
        audio.save()
        return
    if path.suffix == ".aiff":  # ID3 inside the AIFF's own chunk
        audio = AIFF(path)
        audio.add_tags()
        tags = audio.tags
    else:
        tags = ID3()
    frames = {"title": TIT2, "artist": TPE1, "album": TALB, "genre": TCON, "date": TDRC,
              "bpm": TBPM, "key": TKEY, "label": TPUB, "tracknumber": TRCK}  # fmt: skip
    for key, frame in frames.items():
        if t.get(key) is not None:
            tags.add(frame(encoding=3, text=[str(t[key])]))
    if t.get("catalognumber"):
        tags.add(TXXX(encoding=3, desc="CATALOGNUMBER", text=[t["catalognumber"]]))
    if t.get("cover"):
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=t["cover"]))
    if path.suffix == ".aiff":
        audio.save()
    else:
        tags.save(path)


def main(root: Path) -> None:
    rnd = random.Random(2026)
    music, inbox = root / "music", root / "import"
    for folder in (music, inbox, root / "config"):
        folder.mkdir(parents=True, exist_ok=True)
    made = []
    for i in range(40):
        artist = ARTISTS[i % len(ARTISTS)]
        genre = rnd.choice(list(GENRES))
        folder, (low, high) = GENRES[genre]
        title = rnd.choice(WORDS) + rnd.choice(MIXES)
        key = rnd.choice(MINOR if rnd.random() < 0.7 else MAJOR)
        t = {
            "title": title, "artist": artist, "album": f"{title.split(' (')[0]} EP",
            "genre": genre if rnd.random() > 0.08 else None,
            "date": str(rnd.randint(2012, 2026)),
            "bpm": rnd.randint(low, high) if rnd.random() > 0.12 else None,
            "key": key if rnd.random() > 0.15 else None,
            "label": rnd.choice(LABELS) if rnd.random() > 0.25 else None,
            "catalognumber": f"{rnd.choice(['SFA', 'LOW', 'NSM', 'HALO'])}{rnd.randint(1, 99):03d}",
            "tracknumber": "1",
            "cover": cover(rnd) if rnd.random() > 0.15 else None,
        }  # fmt: skip
        fmt = "flac" if rnd.random() < 0.55 else "mp3"
        if i == 7:
            fmt = "aiff"
        path = music / (folder if t["genre"] else "_Unsorted") / f"{artist} - {title}.{fmt}"
        path.parent.mkdir(parents=True, exist_ok=True)
        seconds = rnd.uniform(200, 420)
        silence(path, seconds, fmt)
        tag(path, t)
        made.append((path, t, seconds))
        print("library", path.relative_to(root))

    # Copies for the Duplicates page: a FLAC of a well-tagged MP3 (the better sound with fewer
    # tags: keep it, take the tags over), and an MP3 bought twice.
    for path, t, seconds in made:
        if path.suffix == ".mp3" and t["label"] and t["genre"]:
            flac = path.parent / f"{t['artist']} - {t['title']} [FLAC].flac"
            silence(flac, seconds, "flac", noise=True)
            tag(flac, {"title": t["title"], "artist": t["artist"], "bpm": t["bpm"]})
            print("copy", flac.relative_to(root))
            break
    path, t, seconds = next(m for m in made if m[0].suffix == ".mp3" and m[1]["cover"])
    twice = music / "Downloads" / path.name
    twice.parent.mkdir(exist_ok=True)
    twice.write_bytes(path.read_bytes())
    print("copy", twice.relative_to(root))

    # New tracks in the inbox: some tagged, some with only a telling filename.
    for name, t in [
        ("Polar Tides - Glasshouse (Extended Mix) [174 Am].mp3", {}),
        ("Echo Meridian - Small Hours (VIP).mp3", {}),
        ("Kite Signal - Northern Line.flac", {"title": "Northern Line", "artist": "Kite Signal",
                                              "genre": "dnb", "bpm": 174}),
        ("Mira Vale - Sea Glass (Dub).flac", {"title": "Sea Glass (Dub)", "artist": "Mira Vale",
                                             "genre": "Deep House", "bpm": 122, "key": "Fm",
                                             "label": "Tidewater", "cover": cover(rnd)}),
    ]:  # fmt: skip
        path = inbox / name
        silence(path, rnd.uniform(220, 380), path.suffix[1:])
        if t:
            tag(path, t)
        print("inbox", path.relative_to(root))


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "dev/showcase"))

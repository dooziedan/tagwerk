"""How fast are Tagwerk's pages with a big library? (Roadmap: hardening on the real library.)

Builds a made-up library database (no audio files) of the given size in a temporary folder:
tracks with typical tags, raw tag fields, audio analyses, applied changes, pending changes,
final tracks and some copies. Then it opens every main page a few times and prints how long
each took, plus the memory the process needed. Nothing outside the temporary folder is touched.

    .venv/bin/python scripts/benchmark.py            # 20,000 tracks
    .venv/bin/python scripts/benchmark.py --tracks 50000
"""

import argparse
import json
import os
import random
import resource
import statistics
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

GENRES = ["Drum & Bass", "Drum & Bass; Liquid", "Drum & Bass; Neurofunk", "House", "Deep House",
          "Tech House", "Techno", "Melodic Techno", "Trance", "Dubstep", "UK Garage", "Breaks",
          "Disco", "Nu Disco", "Hip-Hop", "Pop", "Electronic", None]  # fmt: skip
FORMATS = ["mp3"] * 6 + ["flac"] * 3 + ["wav", "aiff", "m4a"]
RAW_ID3 = ["TIT2", "TPE1", "TALB", "TPE2", "TCON", "TBPM", "TKEY", "TDRC", "TPUB", "TRCK",
           "COMM::eng", "TXXX:CATALOGNUMBER", "APIC:", "TXXX:MusicBrainz Album Id"]  # fmt: skip
PAGES = ["/", "/stats", "/stats?rows=key&cols=bpm", "/tracks", "/tracks?flag=not_set_ready",
         "/tracks?flag=audio_bpm_differs", "/tracks?flag=duplicate", "/tracks?q=love",
         "/tracks?genre=House&sort=bpm", "/artists", "/albums", "/fields", "/duplicates",
         "/changes", "/changes/history", "/final", "/settings"]  # fmt: skip


def build(db_url: str, n: int) -> None:
    from sqlalchemy import insert
    from sqlmodel import Session

    from app.db import get_engine, migrate
    from app.models import (
        AppSetting,
        ChangeEntry,
        ChangeSet,
        FinalTrack,
        LibraryAnalysis,
        PendingChange,
        RawTag,
        Track,
    )

    rnd = random.Random(7)
    migrate(db_url)
    engine = get_engine(db_url)
    now = datetime.now(UTC)
    artists = [f"Artist {i}" for i in range(max(50, n // 12))]
    labels = [f"Label {i}" for i in range(max(20, n // 60))]
    words = ["love", "night", "city", "dream", "fire", "gold", "rain", "river", "light", "deep",
             "sun", "echo", "shadow", "wave"]  # fmt: skip
    tracks = []
    for i in range(1, n + 1):
        fmt = rnd.choice(FORMATS)
        artist = rnd.choice(artists)
        title = " ".join(rnd.sample(words, 2)).title() + f" {i % 997}"
        duration = rnd.uniform(150, 480)
        if i > 10 and rnd.random() < 0.03:  # a copy of an earlier track, other format
            src = tracks[rnd.randrange(len(tracks))]
            artist, title, duration = src["artist"], src["title"], src["duration"] + 1
        bpm = round(rnd.uniform(80, 180), 2) if rnd.random() < 0.8 else None
        key = f"{rnd.randint(1, 12)}{rnd.choice('AB')}" if rnd.random() < 0.75 else None
        tracks.append(
            {
                "id": i,
                "path": f"{artist}/{i:06d} {title}.{fmt}",
                "format": fmt,
                "size": rnd.randint(4_000_000, 90_000_000),
                "mtime": 1.7e9 + i,
                "duration": duration,
                "bitrate": 320000 if fmt in ("mp3", "m4a") else 1411000,
                "sample_rate": 44100,
                "bits_per_sample": 16 if fmt not in ("mp3", "m4a") else None,
                "channels": 2,
                "tag_format": "id3",
                "title": title,
                "artist": artist,
                "album": f"Album {i // 9}" if rnd.random() < 0.6 else None,
                "albumartist": None,
                "year": rnd.randint(1975, 2026) if rnd.random() < 0.85 else None,
                "genre": rnd.choice(GENRES),
                "bpm": bpm,
                "key": key,
                "key_camelot": key,
                "label": rnd.choice(labels) if rnd.random() < 0.7 else None,
                "has_cover": rnd.random() < 0.85,
                "has_lyrics": False,
                "has_lrc": False,
                "mbid_invalid": False,
                "added_at": now - timedelta(days=rnd.randint(0, 5 * 365)),
                "scan_version": 99,
                "scanned_at": now,
            }
        )
    with Session(engine) as session:
        session.execute(insert(Track), tracks)
        raw = [{"track_id": t["id"], "system": "id3", "name": name, "value": "x"}
               for t in tracks for name in RAW_ID3]  # fmt: skip
        for start in range(0, len(raw), 50_000):
            session.execute(insert(RawTag), raw[start : start + 50_000])
        session.execute(
            insert(LibraryAnalysis),
            [
                {"track_id": t["id"], "bpm": t["bpm"] or 120.0, "bpm_sure": True, "key": "8A",
                 "key_sure": True, "detail": "{}", "version": 99, "duration": t["duration"],
                 "analysed_at": now, "decided_bpm": t["bpm"] or 120.0, "decided_bpm_sure": True,
                 "decided_key": "8A", "decided_key_sure": True, "decided_notes": "[]"}
                for t in tracks if rnd.random() < 0.6
            ],
        )  # fmt: skip
        sets = max(10, n // 100)
        session.execute(
            insert(ChangeSet),
            [{"id": s, "applied_at": now - timedelta(days=s), "tracks": 20, "written": 20,
              "failed": 0, "fields": "BPM, Key", "kind": "edit" if s % 4 else "import"}
             for s in range(1, sets + 1)],
        )  # fmt: skip
        session.execute(
            insert(ChangeEntry),
            [{"changeset_id": s, "track_id": rnd.randint(1, n), "path": "x",
              "changes": json.dumps({"bpm": [None, "174"], "key": [None, "Am"]}),
              "sources": json.dumps({"bpm": "audio", "key": "you"}), "undone": False}
             for s in range(1, sets + 1) for _ in range(20)],
        )  # fmt: skip
        session.execute(
            insert(PendingChange),
            [{"track_id": t, "field": "label", "new_value": "New", "source": "you",
              "created_at": now} for t in rnd.sample(range(1, n + 1), min(300, n))],
        )  # fmt: skip
        session.execute(
            insert(FinalTrack),
            [{"track_id": t, "marked_at": now, "mtime": 1.7e9 + t}
             for t in rnd.sample(range(1, n + 1), n // 20)],
        )  # fmt: skip
        session.add(AppSetting(key="setup_done", value="true"))
        session.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tracks", type=int, default=20_000)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "music").mkdir()
        os.environ.update(MUSIC_DIR=str(root / "music"), CONFIG_DIR=str(root / "config"),
                          IMPORT_DIR=str(root / "import"))  # fmt: skip
        from app.config import get_settings

        get_settings.cache_clear()
        settings = get_settings()
        settings.config_dir.mkdir()
        started = time.perf_counter()
        build(settings.database_url, args.tracks)
        size = (settings.config_dir / "tagwerk.db").stat().st_size / 1e6
        took = time.perf_counter() - started
        print(f"Built {args.tracks:,} tracks in {took:.1f} s ({size:.0f} MB database)")

        from fastapi.testclient import TestClient

        from app.duplicates import refresh_library
        from app.main import app

        started = time.perf_counter()
        with TestClient(app) as client:  # start-up: migrations and finding duplicates
            print(f"Start-up (migrations, duplicates): {time.perf_counter() - started:.2f} s")
            from app.analysis import refresh_all
            from app.db import get_engine

            for name, work in [
                ("Duplicates after a scan", lambda: refresh_library(
                    get_engine(settings.database_url), settings.music_dir)),
                ("BPM/key decisions after a scan", lambda: refresh_all(
                    get_engine(settings.database_url))),
            ]:  # fmt: skip
                started = time.perf_counter()
                work()
                print(f"{name}: {time.perf_counter() - started:.2f} s")
            print(f"\n{'Page':42} {'median':>8} {'slowest':>8}")
            for url in PAGES:
                times = []
                for _ in range(args.runs):
                    started = time.perf_counter()
                    response = client.get(url)
                    times.append(time.perf_counter() - started)
                    assert response.status_code == 200, (url, response.status_code)
                median, slowest = statistics.median(times) * 1000, max(times) * 1000
                print(f"{url:42} {median:7.0f}ms {slowest:7.0f}ms")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"\nPeak memory of this process: {peak:.0f} MB")


if __name__ == "__main__":
    main()

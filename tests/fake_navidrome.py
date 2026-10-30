"""A stand-in for Navidrome's Subsonic API that scans a real folder (ADR 0046). Its answers have
the shape of saved answers from a real Navidrome 0.64.2. Tests never go online.

It keeps songs the way Navidrome 0.55 and later does: a song whose file is gone is *missing*
(kept, but not found by searches), and a new file with the same **persistent ID** takes the
missing song over, with its ID (and so its plays, stars and playlists). The persistent ID here
is Navidrome's default for files without a MusicBrainz release track ID: album artist, album,
disc and track number, and title (a file without a title tag gets its filename). A file whose
tags change in place keeps its song.
"""

import copy
import io
import json
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.tags import FORMATS, read_file
from tests.conftest import FIXTURES

URL = "http://192.168.1.10:4533"


def saved(name: str) -> dict:
    path = FIXTURES / "online" / f"navidrome_{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))["subsonic-response"]


class ScanningNavidrome:
    """Use as ``monkeypatch.setattr(navidrome.urllib.request, "urlopen", fake)``.

    ``startScan`` starts a scan of ``root`` that is done after ``polls`` more ``getScanStatus``
    calls (a scan already running ignores it). ``scan()`` scans at once. ``down``: every request
    fails like an unreachable Navidrome; ``endless``: a started scan never finishes.
    """

    def __init__(self, root: Path, polls: int = 1) -> None:
        self.root, self.polls = root, polls
        self.songs: dict[str, dict] = {}  # song ID → path, pid, title, album, size, suffix, missing
        self.scans: list[dict[str, tuple]] = []  # what each scan saw: path → (title, album)
        self.calls: list[str] = []  # endpoints asked, in order
        self.running = 0  # polls until the running scan is done; 0: no scan running
        self.last_scan = datetime(2026, 10, 1, tzinfo=UTC)
        self.down = False
        self.endless = False

    def __call__(self, url, timeout):
        parts = urlsplit(url)
        endpoint = parts.path.rsplit("/", 1)[-1]
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.calls.append(endpoint)
        if self.down:
            raise urllib.error.URLError("Connection refused")
        body = {k: v for k, v in saved("getScanStatus").items() if k != "scanStatus"}
        if endpoint == "startScan":
            if not self.running:
                self.running = self.polls
            body["scanStatus"] = self._status()
        elif endpoint == "getScanStatus":
            if self.running and not self.endless:
                self.running -= 1
                if not self.running:
                    self.scan()
            body["scanStatus"] = self._status()
        elif endpoint == "search3":
            words = query["query"].lower().split()
            found = [
                self._child(song_id, song)
                for song_id, song in self.songs.items()
                if not song["missing"] and all(w in song["title"].lower() for w in words)
            ]
            body["searchResult3"] = {"song": found} if found else {}
        return io.BytesIO(json.dumps({"subsonic-response": body}).encode())

    def scan(self) -> None:
        """Read the folder like Navidrome's scanner (hidden files, like Tagwerk's half-copied
        ``.….tagwerk-part``, are left out)."""
        found = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and not path.name.startswith(".") and path.suffix in FORMATS:
                found[path.relative_to(self.root).as_posix()] = self._read(path)
        here = {s["path"]: song_id for song_id, s in self.songs.items() if not s["missing"]}
        for rel, song_id in here.items():
            if rel in found:
                self.songs[song_id] |= found.pop(rel)  # changed in place: the same song
            else:
                self.songs[song_id]["missing"] = True
        for rel, song in found.items():
            taken = next(
                (i for i, s in self.songs.items() if s["missing"] and s["pid"] == song["pid"]),
                None,
            )
            self.songs[taken or f"song-{len(self.songs) + 1}"] = song | {"path": rel}
        self.last_scan = max(datetime.now(UTC), self.last_scan + timedelta(milliseconds=1))
        self.scans.append(
            {s["path"]: (s["title"], s["album"]) for s in self.songs.values() if not s["missing"]}
        )

    def song_at(self, rel: str) -> tuple[str, dict] | None:
        """(song ID, song) of the file at this path, if Navidrome lists it."""
        for song_id, song in self.songs.items():
            if song["path"] == rel and not song["missing"]:
                return song_id, song
        return None

    def _read(self, path: Path) -> dict:
        info = read_file(path)
        title = info.title or path.stem
        artist = info.albumartist or info.artist
        pid = (artist, info.album, info.discnumber, info.tracknumber, title)
        suffix = path.suffix.lstrip(".").lower()
        size = path.stat().st_size
        return {"title": title, "album": info.album, "size": size, "suffix": suffix, "pid": pid,
                "missing": False}  # fmt: skip

    def _status(self) -> dict:
        status = saved("getScanStatus")["scanStatus"]
        return status | {"scanning": bool(self.running),
                         "lastScan": self.last_scan.isoformat().replace("+00:00", "Z")}  # fmt: skip

    def _child(self, song_id: str, song: dict) -> dict:
        """A song as ``search3`` answers it: its path is made up from the tags, not the real one."""
        child = copy.deepcopy(saved("search3")["searchResult3"]["song"][0])
        made_up = f"{song['album'] or '[Unknown Album]'}/{song['title']}.{song['suffix']}"
        child |= {"id": song_id, "title": song["title"], "album": song["album"] or "",
                  "size": song["size"], "suffix": song["suffix"], "path": made_up}  # fmt: skip
        return child

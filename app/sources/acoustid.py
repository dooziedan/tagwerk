"""AcoustID: identifies a track by its sound, even without any tags.

``fpcalc`` (Chromaprint, in the Docker image) computes the fingerprint locally; AcoustID
answers with matching MusicBrainz recordings and how alike the audio is. Needs the owner's
free application key (ACOUSTID_KEY); three requests a second at most.
"""

import json
import shutil
import subprocess

from app.sources.base import Candidate, Query, Source, SourceError


class AcoustID(Source):
    name = "acoustid"
    label = "AcoustID"
    about = "Recognises the sound itself"
    gap = 0.4
    needs = "ACOUSTID_KEY"

    def configured(self) -> bool:
        return bool(self.settings.acoustid_key) and shutil.which("fpcalc") is not None

    def lookup(self, query: Query) -> list[Candidate]:
        if query.path is None:
            return []
        duration, fingerprint = fingerprint_of(query)
        data = self.get_json(
            "https://api.acoustid.org/v2/lookup",
            {"client": self.settings.acoustid_key, "meta": "recordings releasegroups compress",
             "duration": duration, "fingerprint": fingerprint},
        )  # fmt: skip
        if data.get("status") != "ok":
            message = (data.get("error") or {}).get("message", "error")
            raise SourceError(f"AcoustID: {message}")
        candidates = []
        for result in data.get("results", []):
            for recording in result.get("recordings", []):
                if recording.get("title"):
                    candidates.append(_candidate(recording, float(result.get("score", 0))))
        return candidates


def fingerprint_of(query: Query) -> tuple[int, str]:
    """(length in seconds, fingerprint) of the audio, from fpcalc."""
    try:
        done = subprocess.run(
            ["fpcalc", "-json", str(query.path)], capture_output=True, text=True, timeout=120
        )
        result = json.loads(done.stdout)
        return int(result["duration"]), result["fingerprint"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        raise SourceError("AcoustID: couldn't compute the fingerprint of this file") from None


def _candidate(recording: dict, score: float) -> Candidate:
    artist = "".join(
        a.get("name", "") + a.get("joinphrase", "") for a in recording.get("artists", [])
    )
    values = {"title": recording["title"], "artist": artist.strip()}
    groups = recording.get("releasegroups") or []
    album = next((g for g in groups if g.get("type") in ("Single", "EP")), None) or next(
        iter(groups), None
    )
    if album and album.get("title"):
        values["album"] = album["title"]
    return Candidate(
        source="acoustid",
        values=values,
        url=f"https://musicbrainz.org/recording/{recording['id']}",
        duration=recording.get("duration"),
        fingerprint_score=score,
    )

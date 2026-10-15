"""Half or double time: settled by the genre, checked against the audio (ADR 0041).

Stores often list drum & bass at half time (Beatport's 87 for a 174 track). The BPM ranges
(Settings → BPM ranges, ``Drum & Bass: 160-185``, ADR 0042) say which reading a genre has, so
an online 87 for a drum & bass track becomes 174. The tempo Tagwerk measured from the audio
(app/analysis.py) checks the genre in turn: a store calling a 174 BPM track "House" is wrong.

Pure helpers without the database, used by app/identify.py and app/analysis.py.
"""

import json
import re

# Tags store BPM rounded (87.5 -> 88), and doubling a rounded half-time value adds to the
# error (88 x 2 = 176 for a 175 track), so two tempos count as the same within 1.5 %.
TOLERANCE = 0.015

# Settings → BPM ranges, built in: each genre's usual tempo. Subgenres share their main genre's
# range (Liquid is drum & bass). Changing one: e.g. "Dubstep": (70, 75) for half time.
DEFAULT_RANGES: dict[str, tuple[float, float]] = {
    "Drum & Bass": (160, 185),
    "Dubstep": (135, 150),
    "Footwork": (150, 165),
    "Juke": (150, 165),
    "Hardstyle": (145, 160),
    "Hip-Hop": (70, 115),
    "Rap": (70, 115),
    "R&B": (70, 115),
    "House": (110, 150),
    "Tech House": (110, 150),
    "Techno": (110, 150),
    "Trance": (110, 150),
    "Garage": (110, 150),
    "UK Garage": (110, 150),
    "Disco": (110, 150),
    "Nu Disco": (110, 150),
    "Electro": (110, 150),
    "Minimal": (110, 150),
    "Progressive": (110, 150),
}
# Lowest and highest BPM a range may use (Settings → BPM ranges).
RANGE_LIMITS = (40, 300)

# A tempo line of the genre map before 0.27: "Drum & Bass: 160-185 BPM" (BPM optional, "160 - 185").
OLD_RULE = re.compile(r"^(.+?):\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:bpm)?$", re.I)


def split_ranges(text: str) -> tuple[str, dict[str, tuple[float, float]]]:
    """Old tempo lines out of a genre map: ("House > Deep House\nHouse: 110-150 BPM", …) ->
    ("House > Deep House", {"House": (110, 150)}). Everything else stays as written."""
    kept, ranges = [], {}
    for line in text.splitlines(keepends=True):
        if rule := OLD_RULE.match(line.strip()):
            ranges[rule[1].strip()] = tuple(sorted((float(rule[2]), float(rule[3]))))
        else:
            kept.append(line)
    return "".join(kept), ranges


def clean_ranges(value) -> dict[str, tuple[float, float]] | None:
    """BPM ranges as stored (Preferences.bpm_ranges): genre -> (low, high), lowest first.
    Odd entries are left out, a genre listed twice counts once. None means the built-in ones,
    also when the owner's are the same: then they keep up with updates."""
    if not isinstance(value, dict):
        return None
    low_limit, high_limit = RANGE_LIMITS
    ranges, seen = {}, set()
    for name, pair in value.items():
        name = str(name).strip()
        try:
            low, high = sorted(float(v) for v in pair)
        except (TypeError, ValueError):
            continue
        if name and name.lower() not in seen and low_limit <= low and high <= high_limit:
            seen.add(name.lower())
            ranges[name] = (low, high)
    return None if ranges == DEFAULT_RANGES else ranges


def ranges_of(ranges) -> dict[str, tuple[float, float]]:
    """BPM ranges as stored (Preferences.bpm_ranges), None meaning the built-in ones."""
    if ranges is None:
        return dict(DEFAULT_RANGES)
    return {name: (pair[0], pair[1]) for name, pair in ranges.items()}


def near(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE * max(a, b)


def octave(a: float, b: float) -> bool:
    """True if one tempo is half or double the other (87 and 174)."""
    return near(a * 2, b) or near(a, b * 2)


def fold(bpm: float, low: float, high: float) -> float:
    """The reading of a tempo that fits a genre's range: 87 for drum & bass (160-185) is 174.
    Unchanged when it fits already, or when neither half nor double time fits either."""
    if low <= bpm <= high:
        return bpm
    for reading in (bpm * 2, bpm / 2):
        if low <= reading <= high:
            return reading
    return bpm


def heard(tempos: list[float], low: float, high: float) -> bool:
    """True if the audio's tempos (or half or double of them) fit a genre's range: a 174 BPM
    track can be drum & bass or hip-hop (87), not house."""
    return any(low <= t * factor <= high for t in tempos for factor in (1, 2, 0.5))


def audio_tempos(row) -> list[float]:
    """The tempos the audio allows, from a stored analysis (None: not analysed): only the
    measured one when the analysis is sure, else its alternatives too (a triplet feel can make
    the methods hear 116 in a 174 track)."""
    if row is None or row.error or not row.bpm:
        return []
    if row.bpm_sure:
        return [row.bpm]
    try:
        alternatives = json.loads(row.detail or "{}").get("bpm_alternatives", [])
    except ValueError:
        alternatives = []
    return [row.bpm, *alternatives]

"""Musical keys: understand any common notation, display in the one the user picked.

Tools write keys differently: Rekordbox ``Am`` or ``8A``, Mixed In Key ``8A``,
Traktor ``1m``, others ``A minor``. The file keeps whatever it has; Tagwerk parses it into
the Camelot code (``8A``) as a common form and displays that in the chosen notation.

Camelot wheel: numbers 1-12 go round the circle of fifths, A = minor, B = major.
Neighbours on the wheel (same number, or ±1 with the same letter) mix harmonically.
"""

import re

NOTATIONS = {
    "camelot": "Camelot (8A)",
    "openkey": "Open Key (1m)",
    "musical": "Musical (Am)",
}

# Camelot number -> (minor key, major key), in Rekordbox's spelling.
_WHEEL = {
    1: ("Abm", "B"),
    2: ("Ebm", "F#"),
    3: ("Bbm", "Db"),
    4: ("Fm", "Ab"),
    5: ("Cm", "Eb"),
    6: ("Gm", "Bb"),
    7: ("Dm", "F"),
    8: ("Am", "C"),
    9: ("Em", "G"),
    10: ("Bm", "D"),
    11: ("F#m", "A"),
    12: ("Dbm", "E"),
}

# Every pitch spelling -> semitone (C = 0).
_PITCH = {
    "C": 0, "B#": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4,
    "F": 5, "E#": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10,
    "BB": 10, "B": 11, "CB": 11,
}  # fmt: skip

# (semitone, is_minor) -> Camelot code
_TO_CAMELOT = {}
for _number, (_minor, _major) in _WHEEL.items():
    _TO_CAMELOT[(_PITCH[_minor[:-1].upper()], True)] = f"{_number}A"
    _TO_CAMELOT[(_PITCH[_major.upper()], False)] = f"{_number}B"

_CAMELOT_RE = re.compile(r"^0?(1[0-2]|[1-9])\s*([AB])$", re.I)
_OPENKEY_RE = re.compile(r"^0?(1[0-2]|[1-9])\s*([MD])$", re.I)
_MUSICAL_RE = re.compile(
    r"^([A-G])\s*([#B♯♭]?)\s*(M|MIN|MINOR|MAJ|MAJOR|DUR|MOLL)?$",
    re.I,
)

# All 24 Camelot codes in wheel order: 1A, 1B, 2A, 2B, ...
CAMELOT_CODES = [f"{n}{letter}" for n in range(1, 13) for letter in "AB"]


def to_camelot(raw: str | None) -> str | None:
    """Parse a key in any common notation. Returns e.g. '8A', or None if not a key."""
    if not raw:
        return None
    text = raw.strip().replace("♯", "#").replace("♭", "b")
    if match := _CAMELOT_RE.match(text):
        return f"{int(match.group(1))}{match.group(2).upper()}"
    if match := _OPENKEY_RE.match(text):
        # Open Key 1m = Am = Camelot 8A, so Camelot = Open Key + 7 (wrapping at 12).
        number = (int(match.group(1)) + 6) % 12 + 1
        return f"{number}{'A' if match.group(2).lower() == 'm' else 'B'}"
    if match := _MUSICAL_RE.match(text):
        letter, accidental, quality = match.groups()
        pitch = _PITCH.get((letter + accidental).upper())
        if pitch is None:
            return None
        # "m" alone means minor; uppercase "M" is sometimes used for major, but rarely.
        is_minor = bool(quality) and quality.lower() in ("m", "min", "minor", "moll")
        return _TO_CAMELOT[(pitch, is_minor)]
    return None


def display(camelot: str | None, notation: str) -> str:
    """Show a Camelot code ('8A') in the chosen notation: '8A', '1m' or 'Am'."""
    if not camelot:
        return ""
    number, letter = int(camelot[:-1]), camelot[-1]
    if notation == "openkey":
        return f"{(number + 4) % 12 + 1}{'m' if letter == 'A' else 'd'}"
    if notation == "musical":
        minor, major = _WHEEL[number]
        return minor if letter == "A" else major
    return camelot

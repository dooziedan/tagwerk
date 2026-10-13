"""Half or double time: settled by the genre, checked against the audio (ADR 0041).

Stores often list drum & bass at half time (Beatport's 87 for a 174 track). The genre map's
tempo rules (``Drum & Bass: 160-185 BPM``, app/genres.py) say which reading a genre has, so
an online 87 for a drum & bass track becomes 174. The tempo Tagwerk measured from the audio
(app/analysis.py) checks the genre in turn: a store calling a 174 BPM track "House" is wrong.

Pure helpers without the database, used by app/identify.py and app/analysis.py.
"""

import json

# Tags store BPM rounded (87.5 -> 88), and doubling a rounded half-time value adds to the
# error (88 x 2 = 176 for a 175 track), so two tempos count as the same within 1.5 %.
TOLERANCE = 0.015


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

"""BPM and key from the audio itself (ADR 0017).

Pure analysis: give it a file, get back a BPM and a key, how sure they are, and why.
It only reads the file; storing results and suggesting tags happens elsewhere.

Uses Essentia, imported only when a file is analysed (it is big and slow to load).
Run it by hand to try it on files without changing anything:

    python -m app.audio_analysis FILE...            # results as JSON
    python -m app.audio_analysis --compare FILE...  # next to the file's BPM and key tags

How it decides:

- **BPM**: three methods measure the tempo roughly. Methods often hear half or double the
  tempo (87 instead of 174), or a triplet feel (116 = two thirds of 174). So every answer
  also counts for those related tempos, and the tempo that explains the most answers wins.
  The methods only know steps of about 0.7 BPM near 87 (174 and 176 both come out as
  "86.9"), so the winner is then measured precisely: the beats of the whole track are
  lined up at tempos 0.05 BPM apart, and the best fit counts.
  It is *sure* only when two methods measured it directly and double or half of it is
  not an equally good answer: whether a track is 87 or 174 is then decided later with
  the genre and online sources.
- **Key**: the ``edmm`` profile (made for electronic dance music) decides. Bass-heavy
  music such as drum & bass needs fine frequency steps: sub-bass notes are only 2-3 Hz
  apart, so the audio is looked at in long slices (8192 samples, 0.19 s). It is *sure*
  only when the result stays the same with even longer slices and another profile
  hears the same notes (the same Camelot number; minor or major is ``edmm``'s call).
"""

import argparse
import json
import statistics
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app import keys

# Bump when the method changes, so older results are analysed again.
ANALYSIS_VERSION = 1

SAMPLE_RATE = 44100
# Long DJ mixes would need a lot of memory; the first 15 minutes say enough.
MAX_SECONDS = 15 * 60
# Shorter files don't hold enough beats to measure.
MIN_SECONDS = 10

# Tempos a track can sensibly be given; outside this, related tempos are used instead.
BPM_RANGE = (70.0, 200.0)
# Two tempos within 1.5 % of each other count as the same.
BPM_TOLERANCE = 0.015
# How a method can mishear a tempo: exactly, double, half, or a triplet feel.
BPM_RATIOS = {1.0: "", 2.0: "double", 0.5: "half", 1.5: "3:2", 2 / 3: "2:3"}

KEY_FRAME = 8192
KEY_FRAME_CHECK = 16384
KEY_PROFILE = "edmm"
# Profiles that confirm the notes (Camelot number) of edmm's answer.
KEY_CONFIRMING = ("edma", "bgate", "braw", "krumhansl", "temperley2005")


class AnalysisError(Exception):
    """The file can't be analysed (unreadable, silent, too short)."""


@dataclass
class Analysis:
    """What the audio says about one file."""

    bpm: float | None = None
    bpm_sure: bool = False
    # Other tempos that fit, e.g. 173.8 for a track measured at 86.9.
    bpm_alternatives: list[float] = field(default_factory=list)
    key: str | None = None  # Camelot code, e.g. "7A"
    key_sure: bool = False
    key_alternatives: list[str] = field(default_factory=list)
    # Plain-language reasons, shown to the owner.
    notes: list[str] = field(default_factory=list)
    # Every method's raw answer, for checking and improving the method.
    votes: dict = field(default_factory=dict)
    seconds: float = 0.0
    error: str | None = None
    version: int = ANALYSIS_VERSION


def analyse(path: Path) -> Analysis:
    """Analyse one file. Never raises: problems end up in ``error``."""
    try:
        audio = decode(path)
        bpm_votes = tempo_votes(audio)
        key_votes_ = key_votes(audio)
        result = Analysis(seconds=round(len(audio) / SAMPLE_RATE, 1))
        result.votes = {"bpm": bpm_votes, "key": key_votes_}
        result.bpm, result.bpm_sure, result.bpm_alternatives, bpm_note = choose_bpm(
            bpm_votes, refine=lambda bpm: refine_tempo(audio, bpm)
        )
    except AnalysisError as error:
        return Analysis(error=str(error))
    except Exception as error:  # an odd file must not stop a batch
        return Analysis(error=f"Analysis failed: {error}")
    result.key, result.key_sure, result.key_alternatives, key_note = choose_key(key_votes_)
    result.notes = [note for note in (bpm_note, key_note) if note]
    return result


# --- Reading the audio -----------------------------------------------------------------


def decode(path: Path):
    """The file's sound as mono samples (numpy float32), via ffmpeg."""
    import numpy as np

    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-t", str(MAX_SECONDS),
             "-map", "0:a:0", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"],
            capture_output=True,
            check=False,
        )  # fmt: skip
    except FileNotFoundError as error:
        raise AnalysisError("ffmpeg is not installed") from error
    if done.returncode != 0:
        message = done.stderr.decode(errors="replace").strip().splitlines()
        raise AnalysisError(f"Can't read the audio: {message[-1] if message else 'ffmpeg failed'}")
    audio = np.frombuffer(done.stdout, dtype=np.float32).copy()
    if len(audio) < MIN_SECONDS * SAMPLE_RATE:
        raise AnalysisError(f"Too short to analyse (under {MIN_SECONDS} seconds)")
    if float(np.sqrt(np.mean(audio**2))) < 1e-4:
        raise AnalysisError("The audio is silent")
    return audio


def _essentia():
    import essentia
    import essentia.standard

    essentia.log.infoActive = False
    essentia.log.warningActive = False
    return essentia.standard


# --- BPM -------------------------------------------------------------------------------


def tempo_votes(audio) -> dict[str, float]:
    """Each tempo method's answer in BPM."""
    es = _essentia()
    return {
        "multifeature": round(float(es.RhythmExtractor2013(method="multifeature")(audio)[0]), 2),
        "degara": round(float(es.RhythmExtractor2013(method="degara")(audio)[0]), 2),
        "percival": round(float(es.PercivalBpmEstimator()(audio)), 2),
    }


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= BPM_TOLERANCE * max(a, b)


def choose_bpm(
    votes: dict[str, float], refine: Callable[[float], float | None] | None = None
) -> tuple[float | None, bool, list[float], str]:
    """Pick the tempo that explains the most answers, then measure it precisely (``refine``).

    Returns (bpm, sure, alternatives, note).
    """
    answers = {name: bpm for name, bpm in votes.items() if bpm and bpm > 0}
    if not answers:
        return None, False, [], "No beat found"

    # Every tempo some answer could mean, and which answers support it.
    candidates = []
    for bpm in answers.values():
        for ratio in BPM_RATIOS:
            tempo = bpm * ratio
            if not BPM_RANGE[0] <= tempo <= BPM_RANGE[1]:
                continue
            support = {}  # method -> its answer scaled to this tempo
            direct = 0
            for name, other in answers.items():
                for other_ratio in BPM_RATIOS:
                    if _close(other * other_ratio, tempo):
                        support[name] = other * other_ratio
                        direct += other_ratio == 1.0
                        break
            value = round(statistics.median(support.values()), 1)
            candidates.append((len(support), direct, value))
    if not candidates:
        return None, False, [], "The measured tempos are outside 70-200 BPM"

    # Most answers explained first, then most answers measured directly.
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    support, direct, rough = candidates[0]
    precise = refine(rough) if refine else None
    bpm = round(precise, 1) if precise else rough

    # Double and half time stay possible unless they fall outside the range.
    octave = [round(v, 1) for v in (bpm * 2, bpm / 2) if BPM_RANGE[0] <= v <= BPM_RANGE[1]]
    # Alternatives: double/half time, and other tempos a method really measured.
    alternatives: list[float] = []
    heard = [value for _, direct_, value in candidates if direct_]
    for value in octave + heard:
        if not _close(value, bpm) and not any(_close(value, a) for a in alternatives):
            alternatives.append(value)

    sure = direct >= 2 and not octave
    total = len(answers)
    if direct == total:
        note = f"All {total} tempo methods measured {rough:g} BPM"
    elif direct >= 2:
        note = f"{direct} of {total} tempo methods measured {rough:g} BPM"
    else:
        heard = ", ".join(f"{v:g}" for v in sorted(answers.values()))
        note = f"The tempo methods heard {heard} BPM; {rough:g} explains them best"
    if bpm != rough:
        note += f", precisely {bpm:g}"
    if octave:
        note += f"; could also be {' or '.join(f'{v:g}' for v in octave)} (half or double time)"
    return bpm, sure, alternatives, note


def _onset_strength(audio, hop: int = 128, size: int = 1024):
    """How much new sound starts in each moment (``SAMPLE_RATE / hop`` values per second).

    Spectral flux: the increase in loudness per frequency from one short slice to the
    next. Worked out in blocks, so a long mix doesn't need gigabytes of memory.
    """
    import numpy as np

    window = np.hanning(size).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(audio, size)[::hop]
    flux = []
    previous = None
    for start in range(0, len(frames), 4096):
        block = frames[start : start + 4096] * window
        spectrum = np.log1p(1000 * np.abs(np.fft.rfft(block, axis=1))).astype(np.float32)
        if previous is not None:
            spectrum = np.vstack([previous, spectrum])
        flux.append(np.maximum(np.diff(spectrum, axis=0), 0).sum(axis=1))
        previous = spectrum[-1:]
    strength = np.concatenate(flux)
    # Remove slow changes (a build-up getting louder), keep the hits.
    strength -= np.convolve(strength, np.ones(64) / 64, mode="same")
    return np.maximum(strength, 0), SAMPLE_RATE / hop


def refine_tempo(audio, bpm: float, spread: float = 0.03, beats: int = 64) -> float | None:
    """The exact tempo near ``bpm`` (within 3 %, in steps of 0.05 BPM).

    Compares the track with itself shifted by 1, 2, ... 64 beats: at the right tempo the
    hits line up every time, and over 64 beats even a 0.05 BPM error adds up to a miss.
    None if no tempo lines up (no steady beat).
    """
    import numpy as np

    strength, rate = _onset_strength(audio)
    strength = strength - strength.mean()
    n = len(strength)
    spectrum = np.fft.rfft(strength, 2 * n)
    similarity = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    if similarity[0] <= 0:
        return None
    similarity /= similarity[0]

    best, best_score = None, 0.0
    for tempo in np.arange(bpm * (1 - spread), bpm * (1 + spread), 0.05):
        shifts = 60 / tempo * rate * np.arange(1, beats + 1)
        shifts = shifts[shifts < n - 1]
        whole = shifts.astype(int)
        part = shifts - whole
        score = float(np.sum(similarity[whole] * (1 - part) + similarity[whole + 1] * part))
        if score > best_score:
            best, best_score = float(tempo), score
    return best


# --- Key -------------------------------------------------------------------------------


def key_votes(audio) -> dict[str, str]:
    """Each key profile's answer as a Camelot code (``edmm@16384`` = longer slices)."""
    es = _essentia()

    def camelot(profile: str, frame: int) -> str | None:
        key, scale, _strength = es.KeyExtractor(
            profileType=profile, frameSize=frame, hopSize=frame, hpcpSize=36
        )(audio)
        return keys.to_camelot(f"{key} {'minor' if scale == 'minor' else 'major'}")

    votes = {KEY_PROFILE: camelot(KEY_PROFILE, KEY_FRAME)}
    votes[f"{KEY_PROFILE}@{KEY_FRAME_CHECK}"] = camelot(KEY_PROFILE, KEY_FRAME_CHECK)
    for profile in KEY_CONFIRMING:
        votes[profile] = camelot(profile, KEY_FRAME)
    return votes


def _number(camelot: str) -> str:
    return camelot[:-1]


def choose_key(votes: dict[str, str | None]) -> tuple[str | None, bool, list[str], str]:
    """edmm decides; sure when it holds with longer slices and another profile agrees.

    Returns (key, sure, alternatives, note).
    """
    key = votes.get(KEY_PROFILE)
    if not key:
        return None, False, [], "No key found"
    check = votes.get(f"{KEY_PROFILE}@{KEY_FRAME_CHECK}")
    confirming = [
        name for name in KEY_CONFIRMING if votes.get(name) and _number(votes[name]) == _number(key)
    ]
    others = [votes[name] for name in KEY_CONFIRMING if votes.get(name)]
    # What the other profiles hear most, when it is other notes (another Camelot number):
    # edmm is sometimes wrong about the mode of the home note (E-flat minor for major).
    most_heard = max(others, key=others.count) if others else None
    alternatives = [check] if check and check != key else []
    if most_heard and _number(most_heard) != _number(key) and most_heard not in alternatives:
        alternatives.append(most_heard)
    if check != key:
        return key, False, alternatives, f"Key {key} or {check}: the result changes with detail"
    if not confirming:
        heard = ", ".join(sorted(set(others)))
        return key, False, alternatives, f"Key {key}; other methods hear {heard}"
    return key, True, [], f"Key {key}, confirmed by {len(confirming)} other methods"


# --- By hand ---------------------------------------------------------------------------


def _compare(path: Path, result: Analysis) -> dict:
    """The file's own BPM and key tags next to the result."""
    from app import tags

    try:
        info = tags.read_file(path)
    except Exception as error:
        return {"error": f"Can't read tags: {error}"}
    tag_key = keys.to_camelot(info.key)
    tag_bpm = info.bpm or None
    return {
        "bpm": tag_bpm,
        "key": tag_key,
        "bpm_matches": bool(tag_bpm and result.bpm and _close(tag_bpm, result.bpm)),
        "bpm_in_alternatives": bool(
            tag_bpm and any(_close(tag_bpm, v) for v in result.bpm_alternatives)
        ),
        "key_matches": bool(tag_key and tag_key == result.key),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BPM and key from the audio (read-only).")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--compare", action="store_true", help="show the file's own tags too")
    args = parser.parse_args(argv)
    for path in args.files:
        result = analyse(path)
        out = {"file": str(path), **asdict(result)}
        if args.compare and not result.error:
            out["tags"] = _compare(path, result)
        print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

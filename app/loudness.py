"""Loudness from the audio, and whether a track's ReplayGain tags match it (ADR 0029).

Every library track is measured the same way, with ffmpeg's EBU R128 meter (``ebur128``):
the integrated loudness in LUFS and the true peak. ReplayGain 2.0 plays every track at
-18 LUFS, so a track's gain is ``-18 - loudness``: a track measured at -7 LUFS gets
-11.00 dB. Only reads files; the gains become pending changes when the owner asks.

Why check tags that are already there: older taggers used ReplayGain 1, whose reference is
about 4 dB louder (89 dB). A library with both kinds is levelled unevenly although every
track "has ReplayGain", and tags copied from other releases or edits don't fit the file.
"""

import re
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import changes, writer
from app.models import FinalTrack, LibraryLoudness, PendingChange, Track

# Bump when the measurement changes, so older results are measured again.
LOUDNESS_VERSION = 1
REFERENCE = -18.0  # LUFS: the level ReplayGain 2.0 plays every track at
# Tags within half a dB of the measurement are fine: meters differ by a tenth or two,
# and half a dB is below what anyone hears when mixing.
TOLERANCE = 0.5
# ReplayGain 1 measured against 89 dB, about -14 LUFS: its gains are about 4 dB higher.
OLD_REPLAYGAIN = (3.0, 5.0)
TIMEOUT = 600  # seconds; a long mix takes a while
NICENESS = 10

_INTEGRATED = re.compile(r"^\s*I:\s+(-?[\d.]+|-inf)\s+LUFS", re.MULTILINE)
_PEAK = re.compile(r"^\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS", re.MULTILINE)


class LoudnessError(Exception):
    """The file can't be measured (unreadable, silent)."""


# --- Measuring ------------------------------------------------------------------------------


def measure(path: Path) -> dict:
    """Integrated loudness (LUFS) and true peak (linear, 1.0 = full scale) of a file.

    Never raises: ``{"lufs": -7.0, "peak": 1.12}`` or ``{"error": "…"}``.
    """
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-map", "0:a:0",
               "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]  # fmt: skip
    if shutil.which("nice"):
        command = ["nice", "-n", str(NICENESS), *command]
    try:
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        return {"error": "ffmpeg is not installed"}
    except subprocess.TimeoutExpired:
        return {"error": f"Measuring took longer than {TIMEOUT // 60} minutes"}
    output = done.stderr.decode(errors="replace")
    try:
        return parse(output) if done.returncode == 0 else _failed(output)
    except LoudnessError as error:
        return {"error": str(error)}


def parse(output: str) -> dict:
    """The summary ffmpeg's ebur128 filter prints at the end."""
    loudness, peak = _INTEGRATED.findall(output), _PEAK.findall(output)
    if not loudness or not peak:
        raise LoudnessError("ffmpeg gave no loudness for this file")
    lufs = float(loudness[-1])  # "-inf" for silence
    if lufs <= -70:
        raise LoudnessError("The audio is silent")
    return {"lufs": lufs, "peak": round(10 ** (float(peak[-1]) / 20), 6)}


def _failed(output: str) -> dict:
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return {"error": f"Can't read the audio: {lines[-1] if lines else 'ffmpeg failed'}"}


def fresh(row: LibraryLoudness | None, track: Track) -> bool:
    """True if the stored result still holds: writing tags doesn't change the sound, so only
    a newer method or a different length (the file was replaced) asks for a new one."""
    if row is None or row.version != LOUDNESS_VERSION:
        return False
    if row.duration is None or track.duration is None:
        return row.duration == track.duration
    return abs(row.duration - track.duration) < 1


def store(session: Session, track_id: int, found: dict, duration: float | None) -> None:
    row = session.get(LibraryLoudness, track_id) or LibraryLoudness(track_id=track_id)
    row.lufs, row.peak, row.error = found.get("lufs"), found.get("peak"), found.get("error")
    row.version, row.duration, row.measured_at = LOUDNESS_VERSION, duration, datetime.now(UTC)
    session.add(row)
    session.commit()


def measure_track(engine: Engine, music_dir: Path, track_id: int, force: bool = False) -> bool:
    """Measure one library track unless its result is still fresh. True if it was measured."""
    with Session(engine) as session:
        track = session.get(Track, track_id)
        if track is None or track.error:
            return False
        if not force and fresh(session.get(LibraryLoudness, track_id), track):
            return False
        path, duration = music_dir / track.path, track.duration
    found = measure(path)  # seconds: the database isn't held open meanwhile
    with Session(engine) as session:
        if session.get(Track, track_id) is None:  # deleted meanwhile
            return False
        store(session, track_id, found, duration)
    return True


# --- Checking the tags ----------------------------------------------------------------------

# What a track's ReplayGain looks like next to its measurement, worst first.
STATUSES = {
    "old": "Old ReplayGain 1 value (about 4 dB too loud)",
    "differs": "Doesn't match the audio",
    "missing": "No ReplayGain",
    "no_peak": "Gain right, peak missing",
    "ok": "Matches the audio",
}
TO_FIX = ("old", "differs", "missing", "no_peak")


@dataclass
class Check:
    track: Track
    lufs: float
    gain: str  # what the track gain should be: "-11.00 dB"
    peak: str  # the measured true peak: "1.122018"
    status: str  # a key of STATUSES
    difference: float | None = None  # tag - measured gain, dB
    final: bool = False  # locked: shown, but not fixed
    pending: bool = False  # its fix already waits on the Changes page

    @property
    def label(self) -> str:
        return STATUSES[self.status]

    @property
    def values(self) -> dict[str, str]:
        """The pending changes that fix it (the peak alone if only that is missing)."""
        if self.status == "no_peak":
            return {"replaygain_track_peak": self.peak}
        return {"replaygain_track_gain": self.gain, "replaygain_track_peak": self.peak}


def check(track: Track, row: LibraryLoudness) -> Check:
    """Compare a track's ReplayGain tags with its measured loudness."""
    gain = REFERENCE - row.lufs
    found = Check(track, row.lufs, f"{gain:.2f} dB", f"{row.peak:.6f}", "ok")
    if track.replaygain_track_gain is None:
        found.status = "missing"
        return found
    found.difference = round(track.replaygain_track_gain - gain, 2)
    if abs(found.difference) > TOLERANCE:
        low, high = OLD_REPLAYGAIN
        found.status = "old" if low <= found.difference <= high else "differs"
    elif track.replaygain_track_peak is None and writer.supports(
        track.format, "replaygain_track_peak"
    ):  # Opus has no peak field
        found.status = "no_peak"
    return found


@dataclass
class Overview:
    tracks: int  # library tracks that can be read
    measured: int  # with a loudness
    failed: int  # couldn't be measured (unreadable or silent)
    checks: list[Check]  # every measured track
    unmeasured: list[int]  # track ids without a fresh measurement

    def count(self, status: str) -> int:
        return sum(1 for c in self.checks if c.status == status)

    @property
    def to_fix(self) -> list[Check]:
        order = list(STATUSES)
        found = [c for c in self.checks if c.status in TO_FIX and not (c.final or c.pending)]
        return sorted(found, key=lambda c: (order.index(c.status), -abs(c.difference or 0)))

    @property
    def spread(self) -> tuple[float, float, float] | None:
        """Loudness of the library: the quietest tenth ends, the median, the loudest begins."""
        values = sorted(c.lufs for c in self.checks)
        if len(values) < 2:
            return None
        deciles = statistics.quantiles(values, n=10)
        return deciles[0], statistics.median(values), deciles[-1]


def overview(session: Session) -> Overview:
    tracks = list(session.exec(select(Track).where(Track.error.is_(None))))
    rows = {r.track_id: r for r in session.exec(select(LibraryLoudness))}
    final = set(session.exec(select(FinalTrack.track_id)))
    staged: dict[int, dict[str, str | None]] = {}
    for change in session.exec(
        select(PendingChange).where(col(PendingChange.field).in_(list(writer.REPLAYGAIN)))
    ):
        staged.setdefault(change.track_id, {})[change.field] = change.new_value
    checks, unmeasured, failed = [], [], 0
    for track in tracks:
        row = rows.get(track.id)
        if not fresh(row, track):
            unmeasured.append(track.id)
        elif row.error or row.lufs is None:
            failed += 1
        else:
            found = check(track, row)
            found.final = track.id in final
            mine = staged.get(track.id, {})
            found.pending = all(
                mine.get(name) == value
                for name, value in found.values.items()
                if writer.supports(track.format, name)
            )
            checks.append(found)
    return Overview(len(tracks), len(checks), failed, checks, unmeasured)


def fix_count(session: Session) -> int:
    """Measured tracks whose ReplayGain is missing or off (Home: worth a look)."""
    return len(overview(session).to_fix)


def stage_fixes(session: Session, track_ids: list[int] | None = None) -> int:
    """Pending changes with the measured track gain and peak (all tracks to fix, or only
    these). Final tracks are skipped; Opus gets no peak. Returns how many were saved."""
    wanted = None if track_ids is None else set(track_ids)
    saved = 0
    for found in overview(session).to_fix:
        if wanted is None or found.track.id in wanted:
            saved += changes.stage(session, [found.track.id], found.values, "audio")[0]
    return saved


def track_check(session: Session, track: Track) -> Check | None:
    """The check of one track for its page, or None if it isn't measured (or failed)."""
    row = session.get(LibraryLoudness, track.id)
    if not fresh(row, track) or row.error or row.lufs is None:
        return None
    return check(track, row)

"""BPM and key from the audio of inbox and library tracks: running and storing (ADR 0017).

The analysis itself is in app/audio_analysis.py. Here each file is analysed in **its own
process with low priority** (``nice``): it takes seconds of full CPU per track, and this
way the web pages stay fast, Python's one-thread-at-a-time limit doesn't matter, and an
odd file that crashes the analysis can't take the server down.

Results are kept in ``InboxAnalysis`` / ``LibraryAnalysis``. Results only come from reading
files. ``decide`` combines them with the genre, the filename and online sources (which
settles e.g. 87 or 174 BPM): sure values for empty fields become pending changes for library
tracks and suggestions for inbox tracks; values that differ from a tag are only flagged.
"""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import loudness
from app.audio_analysis import ANALYSIS_VERSION
from app.config import Settings
from app.keys import display, to_camelot
from app.models import (
    InboxAnalysis,
    InboxTrack,
    LibraryAnalysis,
    LibraryLookup,
    PendingChange,
    Track,
)

log = logging.getLogger(__name__)

# A track takes 5-10 s; a 15-minute mix about 25 s. Anything far beyond that is stuck.
TIMEOUT = 300
# Lower priority than the web server (0 = normal, 19 = lowest).
NICENESS = 10


# Memory one analysis may need: about 750 MB for a 15-minute mix, much less for a track.
MEMORY_PER_WORKER = 800 * 1024 * 1024


def worker_count(settings: Settings) -> int:
    """How many tracks to analyse at the same time.

    CPU_CORES if set (one track per core); otherwise the CPU cores the container may use, but
    never more than its memory allows for long mixes.
    """
    if settings.cpu_cores > 0:
        return settings.cpu_cores
    by_memory = max(1, (available_memory() or 1 << 62) // MEMORY_PER_WORKER)
    return max(1, min(available_cpus(), by_memory))


def available_cpus() -> int:
    """CPU cores this container may use: the cores it may run on (``--cpuset-cpus``, Unraid's
    CPU pinning), capped by its CPU limit (``--cpus``, docker-compose ``cpus:``)."""
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cores = os.cpu_count() or 1
    limit = _cgroup_cpu_limit()
    return max(1, min(cores, limit) if limit else cores)


def _cgroup_cpu_limit() -> int | None:
    """The container's CPU limit in whole cores (rounded up), or None without a limit."""
    try:  # cgroup v2 (current Docker and Unraid): "200000 100000" = 2 cores, "max ..." = none
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        return None if quota == "max" else math.ceil(int(quota) / int(period))
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        return math.ceil(quota / period) if quota > 0 else None
    except (OSError, ValueError):
        return None


def available_memory() -> int | None:
    """Bytes the analyses may use: the container's memory limit, else what the host has free."""
    try:
        limit = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if limit != "max":
            return int(limit)
    except (OSError, ValueError):
        pass
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def table(library: bool) -> type[InboxAnalysis] | type[LibraryAnalysis]:
    return LibraryAnalysis if library else InboxAnalysis


def result(session: Session, track_id: int, library: bool = False):
    """The stored analysis of a track, or None."""
    return session.get(table(library), track_id)


def detail(row) -> dict:
    """Alternatives, notes and votes of a stored result."""
    try:
        return json.loads(row.detail or "{}")
    except ValueError:
        return {}


def fresh(row, track) -> bool:
    """True if the stored result still holds for this track.

    Writing tags doesn't change the sound, so only a newer method or a different length
    (the file was replaced) asks for a new analysis.
    """
    if row is None or row.version != ANALYSIS_VERSION:
        return False
    if row.duration is None or track.duration is None:
        return row.duration == track.duration
    return abs(row.duration - track.duration) < 1


def run_analysis(path: Path) -> dict:
    """Analyse one file in a separate, low-priority process. Returns the result as a dict
    (fields of ``audio_analysis.Analysis``), with ``error`` set if it failed."""
    command = [sys.executable, "-m", "app.audio_analysis", str(path)]
    if shutil.which("nice"):
        command = ["nice", "-n", str(NICENESS), *command]
    try:
        done = subprocess.run(command, capture_output=True, timeout=TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return {"error": f"The analysis took longer than {TIMEOUT // 60} minutes"}
    # Essentia prints notes of its own; the result is the last line of JSON.
    for line in reversed(done.stdout.decode(errors="replace").splitlines()):
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    log.warning("Audio analysis of %s failed: %s", path, done.stderr.decode(errors="replace"))
    return {"error": "The analysis stopped unexpectedly"}


def store(session: Session, track_id: int, library: bool, found: dict, duration) -> None:
    """Keep one result (replacing an older one)."""
    model = table(library)
    row = session.get(model, track_id) or model(track_id=track_id)
    row.bpm = found.get("bpm")
    row.bpm_sure = bool(found.get("bpm_sure"))
    row.key = found.get("key")
    row.key_sure = bool(found.get("key_sure"))
    row.detail = json.dumps(
        {
            name: found[name]
            for name in ("bpm_alternatives", "key_alternatives", "notes", "votes", "seconds")
            if name in found
        }
    )
    row.error = found.get("error")
    row.version = found.get("version", ANALYSIS_VERSION)
    row.duration = duration
    row.analysed_at = datetime.now(UTC)
    session.add(row)
    session.commit()


def analyse_track(
    engine: Engine, settings: Settings, track_id: int, library: bool = False, force: bool = False
) -> bool:
    """Analyse one inbox or library track unless its result is still fresh. Library tracks
    also get their loudness measured (app/loudness.py), a quick pass of its own.

    Returns True if anything was analysed. Tracks whose tags couldn't be read are skipped.
    """
    with Session(engine) as session:
        track = session.get(Track if library else InboxTrack, track_id)
        if track is None or track.error:
            return False
        audio_fresh = not force and fresh(result(session, track_id, library), track)
        folder = settings.music_dir if library else settings.import_dir
        path, duration = folder / track.path, track.duration
    measured = library and loudness.measure_track(engine, settings.music_dir, track_id, force)
    if audio_fresh:
        return measured
    # The database isn't held open during the analysis (seconds).
    found = run_analysis(path)
    with Session(engine) as session:
        track = session.get(Track if library else InboxTrack, track_id)
        if track is None:  # imported or deleted meanwhile
            return False
        store(session, track_id, library, found, duration)
        if library:
            stage_sure(session, track)
    return True


def copy_to_library(session: Session, inbox_id: int, track_id: int) -> None:
    """On import: the inbox track's result belongs to the new library track (same sound)."""
    found = session.get(InboxAnalysis, inbox_id)
    if found is None:
        return
    values = found.model_dump(exclude={"track_id"})
    existing = session.get(LibraryAnalysis, track_id)
    if existing:
        session.delete(existing)
        session.flush()
    session.add(LibraryAnalysis(track_id=track_id, **values))


# --- Deciding: the audio together with genre, filename and online sources ------------------

# Tempo ranges by genre: they decide between half and double time (87 or 174). The first
# genre of a track that matches decides ("Liquid; Dubstep" is drum & bass). Words match as
# whole words, so "Electronic" is not "electro".
GENRE_TEMPOS: list[tuple[str, tuple[float, float]]] = [
    (r"drum\s*(?:&|and|n|'n')\s*bass|dnb|d&b|jungle|neurofunk|liquid|jump[ -]?up", (160, 185)),
    (r"dubstep|riddim|brostep", (135, 150)),
    (r"footwork|juke", (150, 165)),
    (r"hardstyle", (145, 160)),
    (r"hip[ -]?hop|rap|r&b|rnb", (70, 115)),
    (r"house|techno|trance|garage|disco|electro|minimal|progressive", (110, 150)),
]
# Tags store BPM rounded (87.5 -> 88), and doubling a rounded half-time value adds to the
# error (88 x 2 = 176 for a 175 track), so hints count as the same tempo within 1.5 %.
HINT_TOLERANCE = 0.015


@dataclass
class Decision:
    """What Tagwerk believes after combining the audio with everything else it knows."""

    bpm: float | None = None
    bpm_sure: bool = False
    key: str | None = None  # Camelot code
    key_sure: bool = False
    bpm_notes: list[str] = field(default_factory=list)  # why, in plain language
    # The genre tag picked a tempo that isn't half or double what the audio hears best (e.g.
    # 116.7 for a 174 track tagged "Trance"): shown as a warning, a wrong genre tag is likely.
    bpm_warning: str = ""
    key_notes: list[str] = field(default_factory=list)

    @property
    def notes(self) -> list[str]:
        return self.bpm_notes + self.key_notes


def genre_tempo(genre: str | None) -> tuple[str, tuple[float, float]] | None:
    """(genre, BPM range) for the first genre of a tag that has a typical tempo."""
    for part in re.split(r"[;,/]", genre or ""):
        for pattern, tempo in GENRE_TEMPOS:
            if re.search(rf"\b(?:{pattern})\b", part, re.I):
                return part.strip(), tempo
    return None


def _near(a: float, b: float) -> bool:
    return abs(a - b) <= HINT_TOLERANCE * max(a, b)


def _octave(a: float, b: float) -> bool:
    """True if one tempo is half or double the other (87 and 174)."""
    return _near(a * 2, b) or _near(a, b * 2)


def decide(
    row,
    genre: str | None,
    bpm_hints: list[tuple[float, str]],
    key_hints: list[tuple[str, str]],
) -> Decision:
    """Combine a stored analysis with the genre and hints [(value, "Deezer"), ...].

    Hints from people or stores (filename, online, the tag) pick between what the audio
    allows (87 or 174; 2A or 5B) and make a value sure when they agree. A hint that fits
    nothing the audio heard makes it unsure: the owner should listen.
    """
    result = Decision()
    if row is None or row.error:
        return result
    more = detail(row)
    if row.bpm:
        _decide_bpm(result, row, more.get("bpm_alternatives", []), genre, bpm_hints)
    if row.key:
        _decide_key(result, row, more.get("key_alternatives", []), key_hints)
    return result


def _decide_bpm(result: Decision, row, alternatives, genre, hints) -> None:
    candidates = [row.bpm, *alternatives]
    chosen, sure = row.bpm, row.bpm_sure
    fits = genre_tempo(genre)
    if fits:
        name, (low, high) = fits
        fitting = [c for c in candidates if low <= c <= high]
        if fitting:
            chosen = fitting[0]
            # Only one reading of the beat fits the genre: that settles half or double time.
            sure = sure or not any(low <= v <= high for v in (chosen / 2, chosen * 2))
            if chosen != row.bpm and not _octave(chosen, row.bpm):
                result.bpm_warning = (
                    f"The audio hears {row.bpm:g} BPM best. Tagwerk chose {chosen:g} only "
                    f"because the genre tag says {name} (usually {low:g}-{high:g} BPM). If "
                    f"this track isn't {name}, correct the genre and analyse again."
                )
            elif chosen != row.bpm:
                result.bpm_notes.append(
                    f"{name} is {low:g}-{high:g} BPM: {chosen:g}, not {row.bpm:g}"
                )
            elif not row.bpm_sure:
                result.bpm_notes.append(f"{chosen:g} BPM fits {name} ({low:g}-{high:g})")
        else:
            sure = False
            result.bpm_notes.append(f"The audio's {row.bpm:g} BPM is unusual for {name}")
    for hint, source in hints:
        # Tempos the audio allows that this hint means: as written first, then as half or
        # double time (stores often list drum & bass at 87).
        direct = [c for c in candidates if _near(hint, c)]
        octave = [c for c in candidates if _near(hint * 2, c) or _near(hint / 2, c)]
        matches = direct + [c for c in octave if c not in direct]
        if not matches:
            if source != "your tag":  # differing tags are what the flags are for
                sure = False
                result.bpm_notes.append(f"{source} says {hint:g} BPM, the audio doesn't")
            continue
        if source == "your tag" and (not direct or (fits and chosen not in direct)):
            continue  # a tag the audio doesn't confirm as it is: that's what the flags are for
        if fits and chosen not in matches:
            continue  # it fits a tempo outside the genre's range: the genre wins
        if not fits:
            chosen = matches[0]
        sure = True
        how = "" if chosen in direct else ", half or double time"
        result.bpm_notes.append(f"{source} agrees ({hint:g} BPM{how})")
        break
    result.bpm, result.bpm_sure = round(chosen, 1), sure


def _decide_key(result: Decision, row, alternatives, hints) -> None:
    chosen, sure = row.key, row.key_sure
    for hint, source in hints:
        if hint == row.key or hint in alternatives:
            chosen, sure = hint, True
            result.key_notes.append(f"{source} agrees on the key ({hint})")
            break
        if source != "your tag":
            sure = False
            result.key_notes.append(f"{source} says key {hint}, the audio hears {row.key}")
    result.key, result.key_sure = chosen, sure


def hints(session: Session, track, library: bool, online: bool = True) -> tuple[list, list]:
    """BPM and key hints for a track: filename, online sources, and the tag itself.

    ``online`` False: the track was never looked up, so don't ask the database (refresh_all).
    """
    from app import identify  # identify -> changes -> ... imports would go in a circle
    from app.proposals import parse_filename

    bpm_hints: list[tuple[float, str]] = []
    key_hints: list[tuple[str, str]] = []
    name = parse_filename(track.path)
    if name.bpm:
        bpm_hints.append((float(name.bpm), "The filename"))
    if name.key and (code := to_camelot(name.key)):
        key_hints.append((code, "The filename"))
    for found in identify.results(session, track.id, library) if online else []:
        best = found.best
        if best and best.values.get("bpm"):
            bpm_hints.append((float(best.values["bpm"]), found.label))
    if track.bpm:
        bpm_hints.append((track.bpm, "your tag"))
    if track.key_camelot:
        key_hints.append((track.key_camelot, "your tag"))
    return bpm_hints, key_hints


def decide_for(
    session: Session, track, library: bool, genre: str | None = None, online: bool = True
) -> Decision:
    """The decision for one track (``genre``: the review page's genre for inbox tracks)."""
    bpm_hints, key_hints = hints(session, track, library, online)
    genre = genre if genre is not None else track.genre
    return decide(result(session, track.id, library), genre, bpm_hints, key_hints)


def refresh(session: Session, track: Track, online: bool = True) -> Decision | None:
    """Work out a library track's decision again and keep it (for the filters)."""
    row = session.get(LibraryAnalysis, track.id)
    if row is None:
        return None
    found = decide_for(session, track, library=True, online=online)
    row.decided_bpm, row.decided_bpm_sure = found.bpm, found.bpm_sure
    row.decided_key, row.decided_key_sure = found.key, found.key_sure
    row.decided_notes = json.dumps(found.notes)
    session.add(row)
    return found


def refresh_all(engine: Engine) -> None:
    """After a scan or apply: tags may have changed, so decisions are worked out again.

    Online results are only read for tracks that were looked up (one query for all of them
    instead of one per track: 7 s → about 2 s at 20,000 tracks)."""
    with Session(engine) as session:
        looked_up = set(session.exec(select(LibraryLookup.track_id)).all())
        pairs = session.exec(
            select(Track, LibraryAnalysis).where(Track.id == LibraryAnalysis.track_id)
        )
        for track, _ in pairs.all():
            refresh(session, track, online=track.id in looked_up)
        session.commit()


def stage_sure(session: Session, track: Track) -> int:
    """Sure BPM and key for empty fields become pending changes (not over the owner's own
    pending edits; final tracks are skipped by changes.stage). Returns how many."""
    from app import changes

    found = refresh(session, track)
    session.commit()
    if found is None:
        return 0
    pending = {
        c.field
        for c in session.exec(select(PendingChange).where(PendingChange.track_id == track.id))
    }
    values = {}
    if found.bpm_sure and found.bpm and not track.bpm and "bpm" not in pending:
        values["bpm"] = f"{found.bpm:g}"
    if found.key_sure and found.key and not track.key and "key" not in pending:
        values["key"] = display(found.key, "musical")
    return changes.stage(session, [track.id], values, "audio")[0] if values else 0


def proposals(session: Session, track: InboxTrack, genre: str | None) -> list:
    """Suggestions for an inbox track's empty BPM and key fields (``genre``: the one the
    review page shows). They replace the filename's and online sources' suggestions, which
    the decision already took into account."""
    from app.proposals import Proposal

    found = decide_for(session, track, library=False, genre=genre)
    result = []
    if found.bpm and not track.bpm:
        reason = "; ".join(["From the audio", *found.bpm_notes])
        result.append(Proposal("bpm", f"{found.bpm:g}", None, "audio", found.bpm_sure, reason))
    if found.key and not track.key:
        reason = "; ".join(["From the audio", *found.key_notes])
        value = display(found.key, "musical")
        result.append(Proposal("key", value, None, "audio", found.key_sure, reason))
    return result


def differences(track: Track, found: Decision) -> list[dict]:
    """Where a library track's tags differ from what the audio surely says.

    [{"field": "bpm", "in_file": 87.0, "audio": 174.0, "how": "half"}, ...]; ``how`` is
    "half" or "double" (time) for BPMs, else "differs".
    """
    result = []
    if found.bpm_sure and found.bpm and track.bpm and not _near(track.bpm, found.bpm):
        how = "differs"
        if _near(track.bpm * 2, found.bpm) or _near(track.bpm, found.bpm * 2):
            how = "half" if track.bpm < found.bpm else "double"
        result.append({"field": "bpm", "in_file": track.bpm, "audio": found.bpm, "how": how})
    if found.key_sure and found.key and track.key_camelot and track.key_camelot != found.key:
        result.append(
            {"field": "key", "in_file": track.key_camelot, "audio": found.key, "how": "differs"}
        )
    return result

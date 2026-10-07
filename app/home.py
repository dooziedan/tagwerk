"""The Home page: what needs the owner now, recently added tracks, a few headline numbers.

Statistics and charts are on their own page (app/stats.py). Every number here uses the same
conditions as the track list (app/library.py) and links to exactly those tracks.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import distinct, func
from sqlmodel import Session, select

from app.library import FLAGS, TrackFilter, count
from app.models import RawTag, Track
from app.preferences import Preferences


@dataclass
class Problem:
    count: int
    noun: str  # "track" or "file": "1 track", "2 tracks"
    text: str  # what's wrong, after it: "with a BPM at probably half or double time"
    url: str
    hint: str = ""  # what to do about it
    warn: bool = True  # False: worth knowing, not a problem


@dataclass
class HomeData:
    tracks: int
    duration: float
    set_ready: int
    added_this_month: int
    added_this_month_url: str
    problems: list[Problem] = field(default_factory=list)
    recent: list[Track] = field(default_factory=list)

    @property
    def set_ready_percent(self) -> int:
        return round(100 * self.set_ready / self.tracks) if self.tracks else 0


# Shown in this order, only when there is something. (flag, noun, text, hint, warn, DJ only)
_FLAG_PROBLEMS = [
    ("unreadable", "file", "couldn't be read", "They may be damaged or still copying.", True,
     False),
    ("audio_bpm_octave", "track", "with a BPM at probably half or double time", "", True, True),
    ("audio_key_differs", "track", "with a key that differs from the audio", "", True, True),
    ("audio_bpm_differs", "track", "with a BPM that differs from the audio", "", True, True),
    ("invalid_mbid", "track", "with other IDs in MusicBrainz fields", "Fix IDs moves them.",
     True, False),
    ("final_changed", "final track", "changed outside Tagwerk", "", True, False),
    ("not_set_ready", "track", "not set-ready yet",
     "Missing title, artist, genre, BPM, key or cover.", False, True),
    ("not_analysed", "track", "without BPM and key from the audio",
     "Analyse them from the list.", False, True),
]  # fmt: skip
RECENT = 10


def home_data(session: Session, prefs: Preferences) -> HomeData:
    dj = prefs.mode == "dj"
    tracks, duration = session.exec(
        select(func.count(Track.id), func.coalesce(func.sum(Track.duration), 0))
    ).one()
    month = datetime.now(UTC).strftime("%Y-%m")
    this_month = TrackFilter(added=month)
    data = HomeData(
        tracks=tracks,
        duration=duration,
        set_ready=count(session, FLAGS["set_ready"][1]),
        added_this_month=count(session, *this_month.conditions()),
        added_this_month_url=this_month.url(),
    )
    for flag, noun, text, hint, warn, dj_only in _FLAG_PROBLEMS:
        if dj_only and not dj:
            continue
        if flag == "invalid_mbid" and not prefs.show_musicbrainz:
            continue
        n = count(session, FLAGS[flag][1])
        if n:
            data.problems.append(Problem(n, noun, text, TrackFilter(flag=flag).url(), hint, warn))
    private = session.exec(
        select(func.count(distinct(RawTag.track_id))).where(
            RawTag.system == "id3", RawTag.name.startswith("PRIV:")
        )
    ).one()
    if private:
        data.problems.append(
            Problem(
                private,
                "file",
                "with private data of other programs (e.g. Traktor)",
                "/fields?q=PRIV%3A",
                "Remove it on its Tag fields page.",
                False,
            )
        )
    data.recent = list(
        session.exec(
            select(Track)
            .where(Track.added_at.is_not(None))
            .order_by(Track.added_at.desc(), Track.path)
            .limit(RECENT)
        ).all()
    )
    return data

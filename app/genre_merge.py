"""Genre spellings: one genre written in several ways, and merging them into one.

"Drum & Bass", "Drum and Bass", "Drum And Bass" and "DnB" are one genre (upper/lower case and
the genre map's spelling rules, the same rule the Statistics page counts with). Merging saves
pending changes that write the spelling the owner picked; nothing reaches the files before
they press Apply on the Changes page. Other genres in the tag stay as they are:
"Drum And Bass; Liquid" -> "Drum & Bass; Liquid".
"""

from collections import Counter
from dataclasses import dataclass

from sqlmodel import Session, select

from app import changes, genres
from app.library import TrackFilter
from app.models import FinalTrack, PendingChange, Track


@dataclass
class Spelling:
    name: str
    tracks: int  # tracks whose genre tag has exactly this spelling


@dataclass
class GenreGroup:
    key: str  # what the spellings share (GenreMap.key), identifies the group in forms
    spellings: list[Spelling]  # most used first
    suggested: str  # the spelling to keep unless the owner picks another
    tracks: int  # tracks with any of the spellings
    url: str  # the track list with all of them

    def tracks_with(self, name: str) -> int:
        """Tracks spelling the genre exactly like this (0: no track does yet)."""
        return next((s.tracks for s in self.spellings if s.name == name), 0)

    @property
    def choices(self) -> list[str]:
        """The spellings to pick from: the suggestion first, then the ones in the files."""
        return list(dict.fromkeys([self.suggested, *(s.name for s in self.spellings)]))


def _split(tag: str) -> list[str]:
    return [g.strip() for g in tag.split(";") if g.strip()]


def _genre_tags(session: Session) -> dict[int, str]:
    """The genre tag of every track that isn't final, with pending genre changes applied:
    a merge builds on what the owner already staged instead of throwing it away."""
    query = select(Track.id, Track.genre).where(Track.genre.is_not(None))
    tags = {track_id: tag for track_id, tag in session.exec(query)}
    for track_id, value in session.exec(
        select(PendingChange.track_id, PendingChange.new_value).where(
            PendingChange.field == "genre"
        )
    ):
        tags[track_id] = value or ""
    for track_id in session.exec(select(FinalTrack.track_id)):
        tags.pop(track_id, None)
    return {i: tag for i, tag in tags.items() if tag}


def groups(session: Session) -> list[GenreGroup]:
    """Genres written in more than one way, the most common first."""
    genre_map = genres.active(session)
    counts: dict[str, Counter[str]] = {}
    tracks: Counter[str] = Counter()
    for tag in session.exec(select(Track.genre).where(Track.genre.is_not(None))):
        names = set(_split(tag))
        for name in names:
            counts.setdefault(genre_map.key(name), Counter())[name] += 1
        for key in {genre_map.key(name) for name in names}:
            tracks[key] += 1
    map_names = set(genre_map.spelling.values())  # how the genre map writes its genres
    result = []
    for key, spelled in counts.items():
        if len(spelled) < 2:
            continue
        # The genre map's name wins ("Drum & Bass"); otherwise the most used spelling.
        in_map = [
            genre_map.canonical(name)
            for name, _ in spelled.most_common()
            if name.lower() in genre_map.spelling or name in map_names
        ]
        suggested = in_map[0] if in_map else spelled.most_common(1)[0][0]
        result.append(
            GenreGroup(
                key=key,
                spellings=[Spelling(n, c) for n, c in spelled.most_common()],
                suggested=suggested,
                tracks=tracks[key],
                url=TrackFilter(genre=suggested).url(),
            )
        )
    return sorted(result, key=lambda g: (-g.tracks, g.key))


def merged(tag: str, agreed: dict[str, str], genre_map: genres.GenreMap) -> str:
    """The genre tag with the agreed spellings: {"drum & bass": "Drum & Bass"} turns
    "Drum And Bass; Liquid" into "Drum & Bass; Liquid". A genre listed twice stays once."""
    names = [agreed.get(genre_map.key(name), name) for name in _split(tag)]
    return "; ".join(dict.fromkeys(names))


def stage_merge(session: Session, agreed: dict[str, str]) -> int:
    """Pending changes that write the agreed spelling of each genre (group key -> spelling)
    into every track that spells it differently. Final tracks are skipped (locked).

    Returns how many pending changes were saved.
    """
    genre_map = genres.active(session)
    agreed = {key: name.strip() for key, name in agreed.items() if name.strip()}
    by_value: dict[str, list[int]] = {}  # tracks that get the same new tag, staged together
    for track_id, tag in _genre_tags(session).items():
        new = merged(tag, agreed, genre_map)
        if _split(new) != _split(tag):  # a spelling changed (not just the spaces)
            by_value.setdefault(new, []).append(track_id)
    saved = 0
    for value, track_ids in by_value.items():
        saved += changes.stage(session, track_ids, {"genre": value}, "genre-merge")[0]
    return saved

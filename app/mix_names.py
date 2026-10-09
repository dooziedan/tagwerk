"""Mix names: titles with "(club remix)" or "[vip]" written in lower case, and fixing them.

The rule is the inbox's clean-up rule (proposals.capitalise_mix_types): track types inside
brackets get a capital letter ("Remix", "Edit", "VIP"), remixer names stay as written.
Fixing saves pending changes; nothing reaches the files before the owner presses Apply on
the Changes page.
"""

from dataclasses import dataclass

from sqlmodel import Session, select

from app import changes
from app.models import FinalTrack, PendingChange, Track
from app.proposals import capitalise_mix_types


@dataclass
class MixNameFix:
    track_id: int
    artist: str | None
    title: str  # as in the file, or as already staged
    fixed: str  # with capital letters


def _titles(session: Session) -> dict[int, tuple[str | None, str]]:
    """Artist and title of every track that isn't final, with pending title changes applied:
    a fix builds on what the owner already staged instead of throwing it away."""
    query = select(Track.id, Track.artist, Track.title).where(Track.title.is_not(None))
    titles = {track_id: (artist, title) for track_id, artist, title in session.exec(query)}
    for track_id, value in session.exec(
        select(PendingChange.track_id, PendingChange.new_value).where(
            PendingChange.field == "title"
        )
    ):
        if track_id in titles:
            titles[track_id] = (titles[track_id][0], value or "")
    for track_id in session.exec(select(FinalTrack.track_id)):
        titles.pop(track_id, None)
    return titles


def fixes(session: Session) -> list[MixNameFix]:
    """Tracks whose title would change, sorted by artist and title."""
    result = [
        MixNameFix(track_id, artist, title, fixed)
        for track_id, (artist, title) in _titles(session).items()
        if title and (fixed := capitalise_mix_types(title)) != title
    ]
    return sorted(result, key=lambda f: ((f.artist or "").lower(), f.title.lower()))


def stage_fixes(session: Session, track_ids: list[int] | None = None) -> int:
    """Pending changes that write the capitalised titles (all tracks, or only these).
    Final tracks are skipped (locked). Returns how many pending changes were saved."""
    wanted = None if track_ids is None else set(track_ids)
    saved = 0
    for fix in fixes(session):
        if wanted is None or fix.track_id in wanted:
            saved += changes.stage(session, [fix.track_id], {"title": fix.fixed}, "mix-names")[0]
    return saved

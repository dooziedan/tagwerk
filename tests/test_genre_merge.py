"""Genre spellings: one genre written in several ways, merged into one through Changes."""

import shutil

from mutagen.flac import FLAC
from sqlmodel import Session, select

from app import changes, genre_merge, genres
from app.changes import WriteProgress
from app.models import FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from tests.conftest import FIXTURES

TAGS = {
    "a": "Drum & Bass",
    "b": "Drum & Bass; Liquid",
    "c": "Drum and Bass",
    "d": "Drum And Bass; Liquid",
    "e": "DnB",
    "f": "House",
    "g": "house; Deep House",
}


def add_tracks(engine, music_dir, tags=TAGS) -> dict[str, int]:
    for name, genre in tags.items():
        path = music_dir / "Unsorted" / f"{name}.flac"
        shutil.copy(FIXTURES / "tagged.flac", path)
        audio = FLAC(path)
        audio["genre"] = genre
        audio.save()
    scan_library(engine, music_dir, ScanProgress())
    with Session(engine) as session:
        return {t.path.rsplit("/", 1)[-1][:-5]: t.id for t in session.exec(select(Track))}


def pending_genres(session) -> dict[int, str | None]:
    rows = session.exec(select(PendingChange).where(PendingChange.field == "genre"))
    return {c.track_id: c.new_value for c in rows}


def test_merged_keeps_other_genres_and_their_order():
    m = genres.DEFAULT
    agreed = {"drum & bass": "Drum & Bass"}
    assert genre_merge.merged("Drum And Bass; Liquid", agreed, m) == "Drum & Bass; Liquid"
    assert genre_merge.merged("Liquid;DnB", agreed, m) == "Liquid; Drum & Bass"
    assert genre_merge.merged("DnB; Drum and Bass", agreed, m) == "Drum & Bass"  # once
    assert genre_merge.merged("House", agreed, m) == "House"


def test_groups_list_genres_written_in_several_ways(engine, music_dir):
    add_tracks(engine, music_dir)
    with Session(engine) as session:
        groups = {g.key: g for g in genre_merge.groups(session)}
    assert set(groups) == {"drum & bass", "house"}  # Liquid and Deep House: one spelling each
    dnb = groups["drum & bass"]
    assert dnb.suggested == "Drum & Bass"  # the genre map's name
    assert dnb.tracks == 5
    assert dnb.tracks_with("Drum & Bass") == 2
    assert dnb.tracks_with("DnB") == 1
    assert groups["house"].choices == ["House", "house"]  # no map rule: the most used first


def test_merging_stages_the_agreed_spelling_and_skips_final_tracks(engine, music_dir):
    ids = add_tracks(engine, music_dir)
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids["e"], mtime=0))
        session.commit()
        saved = genre_merge.stage_merge(session, {"drum & bass": "Drum & Bass"})
        assert saved == 2
        assert pending_genres(session) == {
            ids["c"]: "Drum & Bass",
            ids["d"]: "Drum & Bass; Liquid",
        }  # "DnB" is final: locked


def test_merging_builds_on_a_staged_genre(engine, music_dir):
    ids = add_tracks(engine, music_dir)
    with Session(engine) as session:
        changes.stage(session, [ids["f"]], {"genre": "House; Drum and Bass"})
        genre_merge.stage_merge(session, {"drum & bass": "Drum & Bass"})
        assert pending_genres(session)[ids["f"]] == "House; Drum & Bass"


def test_the_merge_page_creates_changes_that_apply_to_the_files(client, engine, settings):
    ids = add_tracks(engine, settings.music_dir)
    page = client.get("/genres")
    assert "Drum and Bass" in page.text and "written 4 ways" in page.text
    assert "1 genre written in several ways" not in client.get("/stats").text
    assert "2 genres written in several ways" in client.get("/stats").text

    form = {"merge": ["house"], "agreed:house": "House", "agreed:drum & bass": "DnB"}
    response = client.post("/genres/merge", data=form, follow_redirects=False)
    assert response.headers["location"] == "/changes?saved=1"  # only the ticked genre
    with Session(engine) as session:
        assert pending_genres(session) == {ids["g"]: "House; Deep House"}

    changes.apply_pending(engine, settings.music_dir, WriteProgress(action="apply"))
    assert FLAC(settings.music_dir / "Unsorted" / "g.flac")["genre"] == ["House", "Deep House"]


def test_api(client, engine, settings):
    add_tracks(engine, settings.music_dir)
    groups = client.get("/api/genres/spellings").json()
    assert groups[0]["key"] == "drum & bass" and groups[0]["choices"][0] == "Drum & Bass"
    merged = client.post("/api/genres/merge", json={"agreed": {"drum & bass": "Drum & Bass"}})
    assert merged.json() == {"pending_changes": 3}

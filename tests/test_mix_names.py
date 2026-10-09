"""Mix names: "(club remix)" in library titles written as "(Club Remix)" through Changes."""

from sqlmodel import Session, select

from app import changes, mix_names
from app.changes import WriteProgress
from app.models import ChangeSet, FinalTrack, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.tags import read_file

ALBUM = "Fixture Artist/Fixture Album"
FORMATS = ["mp3", "flac", "wav", "aiff", "m4a", "ogg", "opus"]


def titled(engine, music_dir, titles: dict[str, str]) -> dict[str, int]:
    """Writes these titles into the tagged fixtures (by format) and returns their track ids."""
    scan_library(engine, music_dir, ScanProgress())
    with Session(engine) as session:
        paths = {t.path: t.id for t in session.exec(select(Track))}
        ids = {fmt: paths[f"{ALBUM}/tagged.{fmt}"] for fmt in FORMATS}
        for fmt, title in titles.items():
            changes.stage(session, [ids[fmt]], {"title": title})
    changes.apply_pending(engine, music_dir, WriteProgress())
    return ids


def pending_titles(session) -> dict[int, str | None]:
    rows = session.exec(select(PendingChange).where(PendingChange.field == "title"))
    return {c.track_id: c.new_value for c in rows}


def test_fixes_list_titles_with_lower_case_mix_names(engine, music_dir):
    ids = titled(engine, music_dir, {"mp3": "Rio (club remix)", "flac": "Rio (Club Remix)"})
    with Session(engine) as session:
        found = mix_names.fixes(session)
    assert [(f.track_id, f.title, f.fixed) for f in found] == [
        (ids["mp3"], "Rio (club remix)", "Rio (Club Remix)")
    ]


def test_fixing_writes_capital_letters_into_every_format_and_undo_restores(engine, music_dir):
    titled(engine, music_dir, dict.fromkeys(FORMATS, "Rio (club remix) [vip]"))
    with Session(engine) as session:
        assert mix_names.stage_fixes(session) == len(FORMATS)
        assert {c.source for c in session.exec(select(PendingChange))} == {"mix-names"}
    progress = WriteProgress()
    changes.apply_pending(engine, music_dir, progress)
    assert progress.failed == 0
    for fmt in FORMATS:
        assert read_file(music_dir / ALBUM / f"tagged.{fmt}").title == "Rio (Club Remix) [VIP]"
    with Session(engine) as session:
        assert mix_names.fixes(session) == []
        changeset_id = session.exec(select(ChangeSet).order_by(ChangeSet.id.desc())).first().id

    changes.undo_changeset(engine, music_dir, changeset_id, WriteProgress(action="undo"))
    for fmt in FORMATS:
        assert read_file(music_dir / ALBUM / f"tagged.{fmt}").title == "Rio (club remix) [vip]"


def test_final_tracks_are_skipped_and_staged_titles_are_built_on(engine, music_dir):
    ids = titled(engine, music_dir, {"mp3": "Rio (club remix)", "flac": "Body (radio edit)"})
    with Session(engine) as session:
        session.add(FinalTrack(track_id=ids["flac"], mtime=0))
        session.commit()
        changes.stage(session, [ids["ogg"]], {"title": "Staged (dub)"})
        assert mix_names.stage_fixes(session) == 2
        assert pending_titles(session) == {
            ids["mp3"]: "Rio (Club Remix)",
            ids["ogg"]: "Staged (Dub)",
        }


def test_the_page_stages_only_the_ticked_titles(client, engine, settings):
    ids = titled(engine, settings.music_dir, {"mp3": "Rio (club remix)", "flac": "Body (edit)"})
    assert "with the mix name in lower case" in client.get("/").text
    page = client.get("/mix-names")
    assert "Rio (club remix)" in page.text and "Rio (Club Remix)" in page.text

    response = client.post("/mix-names/fix", data={"track": [ids["flac"]]}, follow_redirects=False)
    assert response.headers["location"] == "/changes?saved=1"
    with Session(engine) as session:
        assert pending_titles(session) == {ids["flac"]: "Body (Edit)"}


def test_api(client, engine, settings):
    ids = titled(engine, settings.music_dir, {"mp3": "Rio (club remix)"})
    assert client.get("/api/mix-names").json() == [
        {
            "track_id": ids["mp3"],
            "artist": "Artist One; Artist Two",
            "title": "Rio (club remix)",
            "fixed": "Rio (Club Remix)",
        }
    ]
    assert client.post("/api/mix-names/fix", json={}).json() == {"pending_changes": 1}

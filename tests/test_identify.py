import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app import identify, preferences
from app.inbox import review, scan_inbox
from app.models import InboxTrack, OnlineLookup
from app.scanner import ScanProgress
from app.sources import acoustid
from app.sources.base import Query, Source, SourceError
from tests.conftest import FIXTURES

ONLINE = FIXTURES / "online"
NAME = "Fisher - Losing It.mp3"


def answer(name: str) -> dict:
    return json.loads((ONLINE / name).read_text())


@pytest.fixture
def web(monkeypatch):
    """The sources get saved answers (real ones from MusicBrainz, iTunes, Deezer)."""
    asked = []

    def get_json(self, url, params=None, headers=None):
        asked.append(url)
        if "musicbrainz.org" in url:
            return answer("mb_search.json")
        if "itunes.apple.com" in url:
            return answer("itunes.json")
        if "api.deezer.com/search" in url:
            return answer("deezer_search.json")
        if "api.deezer.com/track/" in url:
            return answer("deezer_track.json")
        if "api.deezer.com/album/" in url:
            return answer("deezer_album.json")
        if "discogs.com" in url:
            return answer("discogs_search.json")
        if "acoustid.org" in url:
            return answer("acoustid_lookup.json")
        raise SourceError(f"unexpected {url}")

    monkeypatch.setattr(Source, "get_json", get_json)
    monkeypatch.setattr(acoustid, "fingerprint_of", lambda q: (248, "AQAAfingerprint"))
    monkeypatch.setattr(acoustid.shutil, "which", lambda name: "/usr/bin/fpcalc")
    return asked


@pytest.fixture
def track(engine, settings, monkeypatch):
    """An untagged inbox track named "Fisher - Losing It.mp3", 4:08 long."""
    monkeypatch.setattr(settings, "acoustid_key", "test-key")
    monkeypatch.setattr(settings, "discogs_token", "test-token")
    settings.import_dir.mkdir()
    shutil.copy(FIXTURES / "untagged.mp3", settings.import_dir / NAME)
    scan_inbox(engine, settings.import_dir, ScanProgress())
    with Session(engine) as session:
        row = session.exec(select(InboxTrack)).one()
        row.duration = 248.0
        session.commit()
        return row.id


def fields(engine, track_id) -> dict:
    with Session(engine) as session:
        return {f.field: f for f in review(session, session.get(InboxTrack, track_id), FIELDS)}


FIELDS = ["title", "artist", "album", "date", "genre", "label", "catalognumber", "bpm"]


def test_sources_translate_their_answers(web, settings):
    from app.sources.deezer import Deezer
    from app.sources.discogs import Discogs
    from app.sources.itunes import ITunes
    from app.sources.musicbrainz import MusicBrainz

    query = Query("Fisher", "Losing It", 248.0, Path("x.mp3"))
    mb = MusicBrainz(settings).lookup(query)
    assert [c.duration for c in mb] == [401.0, 164.453, 246.0]
    assert "album" not in mb[2].values  # only on compilations ("The Annual 2019")
    itunes = ITunes(settings).lookup(query)[0]
    assert itunes.values["album"] == "Losing It"  # " - Single" dropped
    assert itunes.cover_url.endswith("1000x1000bb.jpg")
    deezer = Deezer(settings).lookup(query)[0]
    expected = {"bpm": "125", "label": "Fisher - Follow the FISH, LLC", "date": "2018-07-13",
                "genre": "Dance"}  # fmt: skip
    assert expected.items() <= deezer.values.items()
    discogs = Discogs(settings.model_copy(update={"discogs_token": "t"})).lookup(query)[0]
    assert discogs.values["catalognumber"] == "CATCH109"
    assert discogs.values["genre"] == "Tech House"


def test_scoring_prefers_the_same_version():
    from app.sources.base import Candidate

    query = Query("Fisher", "Losing It", 248.0)
    same = Candidate("x", {"title": "Losing It", "artist": "FISHER"}, duration=246)
    radio = Candidate("x", {"title": "Losing It (Radio Edit)", "artist": "FISHER"}, duration=163)
    other = Candidate("x", {"title": "Losing It", "artist": "Amiran Fisher"}, duration=150)
    assert identify.score(same, query) == 1.0
    assert identify.score(radio, query) < identify.MATCH
    assert identify.score(other, query) < identify.MATCH


def test_lookup_suggests_what_sources_agree_on(web, engine, settings, track):
    asked = identify.lookup(engine, settings, track)
    assert asked == 5
    found = fields(engine, track)
    assert found["date"].value == "2018-07-13" and found["date"].suggestion.sure
    assert "agree" in found["date"].suggestion.reason
    assert found["album"].value == "Losing It" and found["album"].suggestion.sure
    assert found["catalognumber"].value == "CATCH109"  # only Discogs: check it
    assert not found["catalognumber"].suggestion.sure
    assert found["bpm"].value == "125" and not found["bpm"].suggestion.sure

    # Asked again only when something changed
    web.clear()
    assert identify.lookup(engine, settings, track) == 0 and web == []


def test_file_tags_win_over_online_values(web, engine, settings, track):
    with Session(engine) as session:
        row = session.get(InboxTrack, track)
        row.label = "My Own Label"
        session.commit()
    identify.lookup(engine, settings, track)
    assert fields(engine, track)["label"].origin == "file"


def test_errors_are_kept_and_other_sources_still_answer(web, monkeypatch, engine, settings, track):
    from app.sources.discogs import Discogs

    def refused(self, query):
        raise SourceError("Discogs refused the request: check DISCOGS_TOKEN")

    monkeypatch.setattr(Discogs, "lookup", refused)
    identify.lookup(engine, settings, track)
    with Session(engine) as session:
        results = {f.source: f for f in identify.results(session, track)}
    assert "DISCOGS_TOKEN" in results["discogs"].error
    assert results["itunes"].best is not None


def test_switched_off_sources_are_not_asked(web, engine, settings, track):
    with Session(engine) as session:
        prefs = preferences.load(session)
        preferences.save(session, replace(prefs, online_sources=["itunes"]))
    identify.lookup(engine, settings, track)
    assert all("itunes.apple.com" in url for url in web)


def test_cover_is_downloaded_and_suggested(web, monkeypatch, engine, settings, track):
    from app.jobs import image_store
    from tests.test_writer import PNG

    monkeypatch.setattr(identify, "download_image", lambda url: PNG)
    identify.lookup(engine, settings, track, images=image_store(settings))
    with Session(engine) as session:
        cover = identify.cover_suggestion(session, session.get(InboxTrack, track))
    assert cover and cover.sure and image_store(settings).get(cover.image_id) == PNG


def test_review_page_shows_results_and_takes_them_over(web, client, engine, settings, track):
    identify.lookup(engine, settings, track)
    page = client.get(f"/inbox/{track}").text
    assert "Online sources" in page and "Use these values" in page and "Open at iTunes" in page
    # Folded with a reminder; it doesn't remember being opened on another page.
    assert "online-remind" in page and "Check " in page and " data-remember>" not in page
    client.post(f"/inbox/{track}/online", data={"source": "discogs", "n": "0"})
    with Session(engine) as session:
        values = {f.field: f for f in review(session, session.get(InboxTrack, track), FIELDS)}
    assert values["label"].value == "Catch & Release" and values["label"].origin == "you"
    with Session(engine) as session:
        assert session.exec(select(OnlineLookup)).all()  # results stay for later


@pytest.mark.parametrize(
    ("artist", "title", "expected"),
    [
        ("Sub Focus feat. Kele", "Turn Back Time", ("Sub Focus", "Turn Back Time")),
        ("Netsky", "Rio (feat. Digital Farm Animals)", ("Netsky", "Rio")),
        ("Above & Beyond", "Sun & Moon", ("Above & Beyond", "Sun & Moon")),  # a band, not two
        ("Fisher; Kita Alexander", "Atmosphere", ("Fisher", "Atmosphere")),
    ],
)
def test_searches_use_the_main_artist_and_plain_title(artist, title, expected):
    query = Query(artist, title, None)
    assert (query.search_artist, query.search_title) == expected


@pytest.mark.parametrize(
    ("values", "duration", "fingerprint", "expected"),
    [
        ({"title": "Losing It", "artist": "FISHER"}, 246, None,
         "same title and artist, same length"),
        ({"title": "Losing It", "artist": "FISHER"}, 401, None,
         "same title and artist, but 6:41 long (this file: 4:08)"),
        ({"title": "Losing It (Radio Edit)", "artist": "FISHER"}, 163, None,
         "another version of the title, same artist; 2:43 long (this file: 4:08)"),
        ({"title": "Losing It", "artist": "Fisher"}, None, None,
         "same title and artist; length unknown"),
        ({"title": "Losing It (Hush Remix)", "artist": "FISHER"}, 300, None,
         "another version of the title, same artist; 5:00 long (this file: 4:08)"),
        ({"artist": "Fisher", "album": "Losing It"}, None, None,
         "a release with this track, same artist; length unknown"),
        ({"title": "Losing It", "artist": "FISHER"}, 248, 0.96,
         "the sound matches (96%); same title and artist"),
    ],
)  # fmt: skip
def test_every_score_is_explained(values, duration, fingerprint, expected):
    from app.sources.base import Candidate

    candidate = Candidate("x", values, duration=duration, fingerprint_score=fingerprint)
    assert identify.explain(candidate, Query("Fisher", "Losing It", 248.0)) == expected


def test_review_page_explains_low_matches(web, client, engine, settings, track):
    with Session(engine) as session:
        session.get(InboxTrack, track).duration = 0.4  # a snippet, not the real song
        session.commit()
    identify.lookup(engine, settings, track)
    page = client.get(f"/inbox/{track}").text
    assert "same title and artist, but 4:08 long (this file: 0:00)" in page

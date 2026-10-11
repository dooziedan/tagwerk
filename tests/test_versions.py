"""Longer versions (ADR 0034): Billy Kenny's "Take Me To Church" is 4:09 in the streaming
stores but 5:26 as the Original Mix on Beatport. Tagwerk recognises the longer file and
checks it against Beatport and Discogs' tracklists. Saved real answers, no internet."""

import json
import re

import pytest
from sqlmodel import Session, select

from app import analysis, identify
from app.models import LibraryAnalysis, PendingChange, Track
from app.scanner import ScanProgress, scan_library
from app.sources.base import Candidate, Query, Source, SourceError
from app.sources.beatport import Beatport
from app.sources.discogs import Discogs, _seconds
from tests.test_identify import ONLINE, web  # noqa: F401  (saved answers instead of the internet)

LONG = ONLINE / "long"
LENGTH = 326.4  # the Original Mix: 5:26


@pytest.fixture
def long_web(monkeypatch):
    """Saved answers for "Billy Kenny – Take Me To Church" from every source."""
    names = {
        "musicbrainz.org": "mb_search.json",
        "itunes.apple.com": "itunes.json",
        "api.deezer.com/search": "deezer_search.json",
        "api.deezer.com/track/": "deezer_track.json",
        "api.deezer.com/album/": "deezer_album.json",
        "api.discogs.com/releases/": "discogs_release.json",
        "api.discogs.com/database": "discogs_search.json",
    }

    def get_json(self, url, params=None, headers=None):
        for part, name in names.items():
            if part in url:
                return json.loads((LONG / name).read_text())
        raise SourceError(f"unexpected {url}")

    def get_text(self, url, params=None):
        if "beatport.com" in url:
            return (LONG / "beatport_search.html").read_text()
        raise SourceError(f"unexpected {url}")

    monkeypatch.setattr(Source, "get_json", get_json)
    monkeypatch.setattr(Source, "get_text", get_text)


@pytest.fixture
def track(engine, settings, monkeypatch):
    """A library track "Billy Kenny – Take Me To Church", 5:26 long, nothing else filled in."""
    monkeypatch.setattr(settings, "discogs_token", "test-token")
    scan_library(engine, settings.music_dir, ScanProgress())
    with Session(engine) as session:
        row = session.exec(select(Track).where(Track.path == "Unsorted/untagged.mp3")).one()
        row.artist, row.title, row.duration = "Billy Kenny", "Take Me To Church", LENGTH
        session.commit()
        return row.id


def results(engine, track_id) -> list[identify.Found]:
    with Session(engine) as session:
        return identify.results(session, track_id, library=True)


def pending(engine, track_id) -> dict[str, str]:
    with Session(engine) as session:
        rows = session.exec(select(PendingChange).where(PendingChange.track_id == track_id))
        return {r.field: r.new_value for r in rows}


# --- The sources ----------------------------------------------------------------------------


def test_beatport_has_the_club_version(long_web, settings):
    found = Beatport(settings).lookup(Query("Billy Kenny", "Take Me To Church", LENGTH))
    best = found[0]
    assert best.values["title"] == "Take Me to Church (Original Mix)"
    assert best.duration == pytest.approx(326.375)
    expected = {"artist": "Billy Kenny", "label": "REALM Records", "genre": "Tech House",
                "bpm": "124", "key": "A Minor", "date": "2019-11-15"}  # fmt: skip
    assert expected.items() <= best.values.items()
    assert "catalognumber" not in best.values  # Beatport has a barcode there, not "RLM021"
    assert best.cover_url.startswith("https://") and best.url.endswith("/12551355")


def test_beatport_names_without_its_own_marks(web, settings):  # noqa: F811
    found = Beatport(settings).lookup(Query("Fisher", "Losing It", 248.0))
    assert found[0].values["artist"] == "FISHER"  # Beatport writes "FISHER (OZ)"
    assert found[0].values["title"] == "Losing It (Extended)"


def test_beatport_says_when_its_page_changed(monkeypatch, settings):
    monkeypatch.setattr(Source, "get_text", lambda self, url, params=None: "<html></html>")
    with pytest.raises(SourceError, match="changed its page"):
        Beatport(settings).lookup(Query("Billy Kenny", "Take Me To Church", LENGTH))


def test_discogs_reads_each_version_from_the_tracklist(web, settings):  # noqa: F811
    discogs = Discogs(settings.model_copy(update={"discogs_token": "t"}))
    found = discogs.lookup(Query("Fisher", "Losing It", 248.0))
    assert [(c.values["title"], c.duration) for c in found] == [
        ("Losing It", 248.0),
        ("Losing It (Radio Edit)", 163.0),
    ]
    assert found[0].values["artist"] == "Fisher"  # Discogs writes "Fisher (11)"
    assert found[0].values["catalognumber"] == "CATCH109"  # the release's values stay


def test_each_discogs_release_is_asked_once(web, engine, settings, track):  # noqa: F811
    with Session(engine) as session:  # the versions and the Discogs IDs share one answer
        row = session.get(Track, track)
        row.artist, row.title, row.duration = "Fisher", "Losing It", 248.0
        session.commit()
    identify.lookup(engine, settings, track, library=True)
    assert sum("api.discogs.com/releases/" in url for url in web) == 1


@pytest.mark.parametrize(
    ("text", "seconds"), [("5:26", 326.0), ("1:02:03", 3723.0), ("", None), ("?", None)]
)
def test_discogs_lengths(text, seconds):
    assert _seconds(text) == seconds


def test_the_original_mix_is_the_plain_title():
    query = Query("Billy Kenny", "Take Me To Church", LENGTH)
    original = Candidate(
        "x", {"title": "Take Me to Church (Original Mix)", "artist": "Billy Kenny"}
    )
    original.duration = 326.4
    assert identify.score(original, query) == 1.0
    assert identify.explain(original, query) == "same title and artist, same length"


# --- Recognising the longer version ---------------------------------------------------------


def test_longer_version_is_recognised_and_confirmed(long_web, engine, settings, track):
    identify.lookup(engine, settings, track, library=True)
    longer = identify.longer_version(results(engine, track))
    assert longer.shorter == ["MusicBrainz", "Deezer", "iTunes"]
    assert longer.confirmed == ["Discogs", "Beatport"] and longer.mix == "Original Mix"
    assert longer.text == (
        "MusicBrainz, Deezer and iTunes only have a 4:09 version. "
        "Discogs and Beatport list this 5:26 version (Original Mix)."
    )


def test_the_confirmed_version_fills_empty_fields(long_web, engine, settings, track):
    identify.lookup(engine, settings, track, library=True)
    staged = pending(engine, track)
    assert staged["label"] == "REALM Records"  # Beatport and Discogs agree
    assert staged["genre"] == "Tech House"
    assert staged["date"].startswith("2019")
    assert "catalognumber" not in staged  # only Discogs knows "RLM021": check it
    assert "bpm" not in staged  # only Beatport knows it


def test_a_longer_version_no_source_lists(long_web, engine, settings, track, monkeypatch):
    def nothing(self, url, params=None):
        raise SourceError("Beatport is busy (rate limit); tried again later")

    monkeypatch.setattr(Source, "get_text", nothing)
    monkeypatch.setattr(settings, "discogs_token", "")  # Discogs not set up
    identify.lookup(engine, settings, track, library=True)
    longer = identify.longer_version(results(engine, track))
    assert longer.confirmed == []
    assert longer.text.endswith("This file is 5:26: maybe an extended or club mix. "
                                "No source lists this length yet.")  # fmt: skip
    assert pending(engine, track) == {}  # nothing matches this file well enough


def test_no_note_when_the_stores_have_this_length(web, engine, settings, track):  # noqa: F811
    with Session(engine) as session:  # Fisher's "Losing It", 4:08: the stores sell it
        row = session.get(Track, track)
        row.artist, row.title, row.duration = "Fisher", "Losing It", 248.0
        session.commit()
    identify.lookup(engine, settings, track, library=True)
    assert identify.longer_version(results(engine, track)) is None


def test_other_remixes_are_not_shorter_versions():
    asked = Query("DJ Fresh", "Gold Dust", 340.0)
    remix = Candidate("x", {"title": "Gold Dust (Bou & Used Remix)", "artist": "DJ Fresh"})
    remix.duration = 222.0
    found = [identify.Found("deezer", "Deezer", [remix], asked=asked)]
    assert identify.longer_version(found) is None


def test_a_source_with_a_longer_version_too_doesnt_count():
    asked = Query("Fisher", "Losing It", 330.0)  # an edit between the 4:08 and the 6:41
    original = Candidate("x", {"title": "Losing It", "artist": "Fisher"}, duration=248.0)
    extended = Candidate("x", {"title": "Losing It (Extended Mix)", "artist": "Fisher"})
    extended.duration = 401.0
    both = identify.Found("musicbrainz", "MusicBrainz", [original, extended], asked=asked)
    short = identify.Found("deezer", "Deezer", [original], asked=asked)
    assert identify.longer_version([both, short]).shorter == ["Deezer"]


def test_the_version_words_dont_decide_the_length():
    """Stores name versions loosely: a file tagged "Radio Mix" can be the long Original Mix,
    and Beatport's "Radio Mix" is Deezer's "Radio Edit"."""
    asked = Query("Fisher", "Losing It (Radio Mix)", 401.0)  # mis-tagged: it's the long one

    def version(name, duration):
        return Candidate(
            "x", {"title": f"Losing It ({name})", "artist": "Fisher"}, duration=duration
        )

    beatport = [version("Original Mix", 401.0), version("Radio Mix", 249.0)]
    deezer = [version("Radio Edit", 248.0)]
    longer = identify.longer_version([
        identify.Found("beatport", "Beatport", beatport, asked=asked),
        identify.Found("deezer", "Deezer", deezer, asked=asked),
    ])  # fmt: skip
    assert longer.shorter == ["Deezer"] and longer.confirmed == ["Beatport"]
    assert longer.text == (
        "Deezer only has a 4:08 version. Beatport lists this 6:41 version (Original Mix)."
    )


@pytest.mark.parametrize(
    ("title", "same"),
    [
        ("Losing It", True),
        ("Losing It (Original Mix)", True),
        ("Losing It (Extended Mix)", True),
        ("Losing It (Club Mix)", True),
        ("Losing It - Radio Edit", True),
        ("Losing It (Extended Version)", True),
        ("Losing It (Hush Remix)", False),  # someone else's remix or edit: another track
        ("Losing It (Dimitri Edit)", False),
        ("Losing It (Hush Mix)", False),
    ],
)
def test_version_words_name_the_same_track(title, same):
    asked = Query("Fisher", "Losing It (Radio Mix)", 401.0)
    assert identify._same_track(Candidate("x", {"title": title, "artist": "Fisher"}), asked) is same


def test_a_title_that_is_a_version_word_stays():
    radio = Query("Someone", "Radio", 300.0)
    assert identify._same_track(
        Candidate("x", {"title": "Radio (Club Mix)", "artist": "Someone"}), radio
    )
    assert not identify._same_track(
        Candidate("x", {"title": "Original", "artist": "Someone"}), radio
    )


def test_track_page_says_longer_version(long_web, client, engine, settings, track):
    identify.lookup(engine, settings, track, library=True)
    page = client.get(f"/tracks/{track}").text
    assert "Longer version" in page and "Discogs and Beatport list this 5:26 version" in page


# --- BPM and key ----------------------------------------------------------------------------


def test_beatports_key_is_a_hint_for_the_audio(long_web, engine, settings, track):
    identify.lookup(engine, settings, track, library=True)
    with Session(engine) as session:
        bpm_hints, key_hints = analysis.hints(session, session.get(Track, track), library=True)
    assert (124.0, "Beatport") in bpm_hints and ("8A", "Beatport") in key_hints


@pytest.fixture
def two_stores_agree_on_bpm(web, monkeypatch):  # noqa: F811
    """Beatport sells Fisher's 4:08 version at 125 BPM, and Deezer says 125 too."""
    page = (ONLINE / "beatport_search.html").read_text()
    data = json.loads(re.search(r'json">(.*?)</script>', page, re.S).group(1))
    first = data["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["data"][0]
    first.update(length=248000, mix_name="Original Mix", bpm=125)
    changed = page.replace(
        page[page.index('json">') + 6 : page.index("</script>")], json.dumps(data)
    )
    monkeypatch.setattr(Source, "get_text", lambda self, url, params=None: changed)


def test_the_audio_decides_the_bpm(two_stores_agree_on_bpm, engine, settings, track):
    with Session(engine) as session:
        row = session.get(Track, track)
        row.artist, row.title, row.duration = "Fisher", "Losing It", 248.0
        session.commit()
    identify.lookup(engine, settings, track, library=True)
    assert pending(engine, track)["bpm"] == "125"  # not analysed yet: the stores agree
    with Session(engine) as session:
        for change in session.exec(select(PendingChange)):
            session.delete(change)
        session.add(LibraryAnalysis(track_id=track, bpm=125.0, duration=248.0))
        session.commit()
    identify.lookup(engine, settings, track, force=True, library=True)
    assert "bpm" not in pending(engine, track)  # analysed: the audio decides, stores are hints

"""Genre and BPM weighed together, checked against the audio (ADR 0041)."""

import json
from types import SimpleNamespace

import pytest

from app import analysis, genres, identify, preferences, tempo
from app.models import Track
from app.preferences import Preferences
from app.sources.base import Candidate


def found(source: str, score: float = 0.9, **values) -> identify.Found:
    candidate = Candidate(source, {k: str(v) for k, v in values.items()}, score=score)
    return identify.Found(source, identify.LABELS[source], [candidate])


def suggested(online, track=None, audio=(), genre=None) -> dict:
    track = track or Track(path="a.mp3", title="T", artist="A")
    result = identify.suggestions(
        None, track, set(), found=online, genre_map=genres.DEFAULT, audio=list(audio), genre=genre
    )
    return {p.field: p for p in result}


def analysed(bpm, alternatives=(), sure=False):
    detail = json.dumps({"bpm_alternatives": list(alternatives), "key_alternatives": []})
    return SimpleNamespace(
        error=None, bpm=bpm, bpm_sure=sure, key=None, key_sure=False, detail=detail
    )


# --- BPM ranges (Settings → BPM ranges, ADR 0042) -------------------------------------------


def ranges(text="", **own):
    """A genre map with the owner's BPM ranges (genre=(low, high)); no ranges: the built-in."""
    return genres.of(Preferences(genre_map=text, bpm_ranges=own or None))


def test_the_bpm_ranges_know_tempos_and_the_owner_can_change_them():
    assert genres.DEFAULT.tempo_of("Drum & Bass; Liquid") == ("Drum & Bass", (160, 185))
    assert genres.DEFAULT.tempo_of("Neurofunk") == ("Neurofunk", (160, 185))  # a subgenre
    assert genres.DEFAULT.tempo_of("Melodic House & Techno") == (
        "Melodic House & Techno",
        (110, 150),
    )
    assert genres.DEFAULT.tempo_of("Electronic") is None
    assert ranges().tempo_of("DnB") == ("DnB", (160, 185))  # spellings count
    # An owner who plays dubstep at half time sets its range; subgenres follow.
    own = ranges("Dubstep > Riddim\n", Dubstep=[70, 75])
    assert own.tempo_of("Riddim") == ("Riddim", (70, 75))
    assert own.tempo_of("Drum & Bass") is None  # their own ranges only
    # An own genre map without ranges keeps the built-in ranges.
    assert ranges("Drum & Bass = Drum und Bass\n").tempo_of("Drum und Bass")[1] == (160, 185)
    assert genres.GenreMap.problems("Dubstep: 70-75 BPM\nTechno: 125 - 140\nnonsense") == [3]


def test_old_tempo_lines_in_the_genre_map_move_to_the_bpm_ranges():
    # A map saved with 0.26 holds its tempos as lines: they become the ranges, all of them.
    prefs = preferences._validated(
        Preferences(genre_map="Dubstep > Riddim\nDubstep: 70-75 BPM\nTechno: 125 - 140\n")
    )
    assert prefs.genre_map == "Dubstep > Riddim\n"
    assert prefs.bpm_ranges == {"Dubstep": [70, 75], "Techno": [125, 140]}
    # The built-in tempo lines alone: back to the built-in ranges, which keep up with updates.
    lines = "".join(f"{g}: {lo}-{hi} BPM\n" for g, (lo, hi) in tempo.DEFAULT_RANGES.items())
    prefs = preferences._validated(Preferences(genre_map=genres.DEFAULT_MAP + lines))
    assert prefs.bpm_ranges is None and prefs.genre_map == genres.DEFAULT_MAP
    # With own ranges already, a pasted tempo line is added to them.
    prefs = preferences._validated(
        Preferences(genre_map="House: 120-130 BPM", bpm_ranges={"Techno": [125, 140]})
    )
    assert prefs.genre_map == "" and prefs.bpm_ranges == {"Techno": [125, 140], "House": [120, 130]}


def test_odd_bpm_ranges_are_left_out():
    cleaned = tempo.clean_ranges(
        {"Techno": [140, 125], "techno": [1, 2], "": [80, 90], "Ambient": [10, 20], "X": "fast"}
    )
    assert cleaned == {"Techno": (125, 140)}  # sorted; twice, empty, out of limits, no numbers
    assert tempo.clean_ranges(dict(tempo.DEFAULT_RANGES)) is None  # same as built in
    assert tempo.clean_ranges("nonsense") is None


def test_fold_reads_a_tempo_at_the_genres_speed():
    assert tempo.fold(87, 160, 185) == 174
    assert tempo.fold(174, 160, 185) == 174
    assert tempo.fold(128, 160, 185) == 128  # neither half nor double fits: unchanged
    assert tempo.fold(140, 70, 75) == 70
    assert tempo.heard([174], 160, 185) and tempo.heard([87], 160, 185)
    assert not tempo.heard([174], 110, 150)


# --- Online lookups ------------------------------------------------------------------------


def test_beatports_half_time_bpm_is_read_at_drum_and_bass_speed():
    online = [found("beatport", genre="Drum & Bass", bpm=87), found("deezer", bpm=87)]
    found_ = suggested(online)
    assert found_["genre"].value == "Drum & Bass"
    assert (found_["bpm"].value, found_["bpm"].sure) == ("174", True)
    assert "Beatport says 87: Drum & Bass is 160-185 BPM" in found_["bpm"].reason


def test_the_tracks_own_genre_settles_the_bpm_too():
    track = Track(path="a.mp3", title="T", artist="A", genre="Liquid")
    found_ = suggested([found("deezer", bpm=86, genre="Pop")], track=track)
    assert found_["bpm"].value == "172"


def test_the_measured_tempo_rules_out_a_genre():
    # Two album-level stores say House, Beatport says Drum & Bass. Without the audio the two
    # stores win; the audio hears 174 BPM, which house never is.
    online = [
        found("beatport", score=0.9, genre="Drum & Bass"),
        found("deezer", score=1.0, genre="House"),
        found("itunes", score=1.0, genre="House"),
    ]
    assert (suggested(online)["genre"].value, suggested(online)["genre"].sure) == ("House", True)
    genre = suggested(online, audio=[174])["genre"]
    assert (genre.value, genre.sure) == ("Drum & Bass", False)  # one source: check it
    assert "not House (Deezer + iTunes): the audio hears 174 BPM" in genre.reason


def test_beatports_genre_counts_double():
    online = [found("beatport", genre="Drum & Bass"), found("deezer", genre="Electronic")]
    assert suggested(online)["genre"].value == "Drum & Bass"


def test_a_genre_the_audio_contradicts_is_never_sure():
    online = [found("deezer", genre="House"), found("itunes", genre="House")]
    genre = suggested(online, audio=[174])["genre"]
    assert (genre.value, genre.sure) == ("House", False)
    assert "the audio hears 174 BPM, unusual for House" in genre.reason


def test_use_these_values_takes_the_bpm_at_the_genres_speed():
    candidate = Candidate("beatport", {"genre": "Drum & Bass", "bpm": "87", "title": "T"})
    values = identify.values_to_take(candidate, Track(path="a.mp3"), genres.DEFAULT)
    assert values["bpm"] == "174"
    # The online box shows it that way, and why.
    bpm = next(
        c
        for c in identify.compare(candidate, Track(path="a.mp3"), genres.DEFAULT)
        if c.name == "bpm"
    )
    assert (bpm.value, bpm.note) == ("174", "Beatport says 87: Drum & Bass is 160-185 BPM")


# --- With the audio ------------------------------------------------------------------------


@pytest.mark.parametrize("genre_tag", [None, "Electronic"])
def test_an_online_genre_settles_half_time_before_anyone_tags_it(genre_tag):
    # The audio hears 87 (or 174); only Beatport knows the genre, and gives 87 BPM.
    track = Track(path="a.mp3", genre=genre_tag)
    online = [found("beatport", genre="Drum & Bass", bpm=87)]
    decision = analysis.decide_with(track, None, online, analysed(87.0, [174.0], sure=True))
    assert (decision.bpm, decision.bpm_sure) == (174.0, True)
    assert decision.bpm_notes[0] == "Genre Drum & Bass from Beatport (90% match)"


def test_an_online_genre_the_audio_doesnt_hear_is_ignored():
    track = Track(path="a.mp3")
    online = [found("deezer", genre="House", bpm=87)]
    decision = analysis.decide_with(track, None, online, analysed(87.0, [174.0], sure=True))
    assert decision.bpm == 87.0  # Deezer's 87 matches what the audio hears; House says nothing

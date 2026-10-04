# ruff: noqa: E501  (the example tables read best one case per line)
from datetime import datetime

import pytest

from app.genres import DEFAULT
from app.naming import PatternError, check, filename, folder, values_for

ADDED = datetime(2026, 10, 4)
FULL = values_for(
    {"artist": "Fisher; Kita Alexander", "title": "Losing It (Extended Mix)", "bpm": "126",
     "key": "Am", "genre": "Liquid", "date": "2018-07-13", "label": "Catch & Release"},
    DEFAULT, "camelot", ADDED,
)  # fmt: skip
BARE = values_for({"artist": "Calibre", "title": "Mr Right On"}, DEFAULT, "camelot", ADDED)


@pytest.mark.parametrize(
    ("pattern", "values", "expected"),
    [
        ("{artist} - {title} [{bpm} {key}]", FULL, "Fisher - Losing It (Extended Mix) [126 8A].mp3"),
        ("{artist} - {title} [{bpm} {key}]", BARE, "Calibre - Mr Right On.mp3"),  # empty part gone
        ("{bpm} - {key} - {artist} - {title}", BARE, "Calibre - Mr Right On.mp3"),
        ("{artist} - {title} ({label})", FULL, "Fisher - Losing It (Extended Mix) (Catch & Release).mp3"),
    ],
)  # fmt: skip
def test_filename(pattern, values, expected):
    assert filename(pattern, values, ".mp3") == expected


def test_names_are_safe_on_every_share():
    values = values_for({"artist": "AC/DC", "title": 'What? "Yes": Live'}, DEFAULT, "musical")
    assert filename("{artist} - {title}", values, ".wav") == "AC-DC - What 'Yes' - Live.wav"


def test_key_follows_the_chosen_notation():
    values = values_for({"artist": "A", "title": "T", "key": "8A"}, DEFAULT, "musical")
    assert filename("{title} {key}", values, ".mp3") == "T Am.mp3"


@pytest.mark.parametrize(
    ("layout", "pattern", "values", "genre_folders", "existing", "expected"),
    [
        ("genre", "", FULL, [], ["Drum & Bass", "House"], "Drum & Bass"),  # Liquid -> its main genre
        ("genre", "", FULL, [], ["drum & bass"], "drum & bass"),  # spelled like the folder on disk
        ("genre", "", FULL, [], ["House"], "_Unsorted"),  # no folder yet: proposed, never created
        ("genre", "", FULL, ["House", "Drum & Bass"], [], "Drum & Bass"),  # a ticked main genre
        ("genre", "", FULL, ["House", "Techno"], ["Drum & Bass"], "_Unsorted"),  # not ticked
        ("genre", "", BARE, [], ["House"], "_Unsorted"),
        ("artist", "", FULL, [], [], "Fisher"),
        ("date", "", FULL, [], [], "2026/2026-10"),
        ("custom", "{genre}/{year}", FULL, [], [], "Drum & Bass/2018"),
        ("custom", "{genre}/{year}", BARE, [], [], "_Unsorted"),  # empty subfolders are left out
    ],
)  # fmt: skip
def test_folder(layout, pattern, values, genre_folders, existing, expected):
    assert folder(layout, pattern, values, genre_folders, existing) == expected


def test_check_rejects_unknown_placeholders():
    check("{artist} - {title} [{bpm}]")
    check("{genre}/{added_year}", folders=True)
    with pytest.raises(PatternError, match="Unknown: {titel}"):
        check("{artist} - {titel}")
    with pytest.raises(PatternError, match="Unknown: {title}"):
        check("{genre}/{title}", folders=True)  # filenames never go into folder patterns
    with pytest.raises(PatternError, match="at least one placeholder"):
        check("music")

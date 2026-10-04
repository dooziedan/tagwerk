import pytest

from app.keys import CAMELOT_CODES, display, to_camelot


@pytest.mark.parametrize(
    ("raw", "camelot"),
    [
        ("Am", "8A"),
        ("A minor", "8A"),
        ("Amin", "8A"),
        ("8A", "8A"),
        ("08A", "8A"),
        ("8a", "8A"),
        ("1m", "8A"),  # Open Key
        ("C", "8B"),
        ("C major", "8B"),
        ("1d", "8B"),
        ("F#m", "11A"),
        ("Gbm", "11A"),
        ("F♯m", "11A"),
        ("Bb", "6B"),
        ("A#", "6B"),
        ("Abm", "1A"),
        ("G#m", "1A"),
        ("12B", "12B"),
    ],
)
def test_notations_are_recognized(raw, camelot):
    assert to_camelot(raw) == camelot


@pytest.mark.parametrize("raw", [None, "", "xyz", "13A", "H", "0A"])
def test_non_keys(raw):
    assert to_camelot(raw) is None


@pytest.mark.parametrize("notation", ["camelot", "openkey", "musical"])
def test_every_key_round_trips(notation):
    for code in CAMELOT_CODES:
        assert to_camelot(display(code, notation)) == code


def test_display_examples():
    assert display("8A", "camelot") == "8A"
    assert display("8A", "openkey") == "1m"
    assert display("8A", "musical") == "Am"
    assert display("3B", "musical") == "Db"
    assert display(None, "musical") == ""

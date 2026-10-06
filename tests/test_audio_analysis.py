"""BPM and key from the audio (app/audio_analysis.py).

The choosing rules are tested with made-up method answers, many taken from real tracks;
the full analysis runs once on a generated drum & bass loop.
"""

import json
import shutil
import subprocess

import pytest

from app import audio_analysis
from app.audio_analysis import analyse, choose_bpm, choose_key
from tests.conftest import FIXTURES

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
DNB_LOOP = FIXTURES / "dnb-174-7A.ogg"


# --- BPM -------------------------------------------------------------------------------


def test_house_tempo_all_methods_agree_is_sure():
    bpm, sure, alternatives, note = choose_bpm(
        {"multifeature": 129.99, "degara": 129.99, "percival": 130.01}
    )
    assert bpm == 130.0
    assert sure
    # Half (65) is outside 70-200, double (260) too: nothing to confuse it with.
    assert alternatives == []
    assert note == "All 3 tempo methods measured 130 BPM"


def test_drum_and_bass_heard_at_half_time_keeps_double_as_alternative():
    # The Samurai (174 BPM): every method hears half time.
    bpm, sure, alternatives, note = choose_bpm(
        {"multifeature": 86.89, "degara": 86.67, "percival": 86.86}
    )
    assert bpm == 86.9
    assert not sure  # 87 or 174 is decided later with the genre and online sources
    assert alternatives == [173.8]
    assert "could also be 173.8" in note


def test_triplet_feel_is_explained_by_the_full_tempo():
    # Gold Dust (Fox Stevenson Remix), 174 BPM: two methods hear two thirds of it.
    bpm, sure, alternatives, _ = choose_bpm(
        {"multifeature": 115.63, "degara": 115.69, "percival": 86.86}
    )
    assert bpm == 173.5
    assert not sure
    assert 115.7 in alternatives and 86.8 in alternatives


def test_two_methods_agreeing_win_over_an_outlier():
    # Louie Vega edit, tagged 115.
    bpm, sure, alternatives, note = choose_bpm(
        {"multifeature": 116.9, "degara": 115.01, "percival": 114.84}
    )
    assert bpm == 114.9
    assert sure
    assert 116.9 in alternatives
    assert note == "2 of 3 tempo methods measured 114.9 BPM"


def test_rough_tempo_is_measured_precisely():
    # On My Mind: the methods only say "about 87"; the fine measurement finds 87.5,
    # and double time follows the precise value (175, not 174.4).
    bpm, sure, alternatives, note = choose_bpm(
        {"multifeature": 172.27, "degara": 87.22, "percival": 87.59}, refine=lambda bpm: 87.49
    )
    assert bpm == 87.5
    assert not sure
    assert alternatives[0] == 175.0
    assert note == (
        "2 of 3 tempo methods measured 87.2 BPM, precisely 87.5; "
        "could also be 175 (half or double time)"
    )


def test_no_steady_beat_keeps_the_rough_tempo():
    bpm, *_ = choose_bpm({"multifeature": 130.0, "degara": 130.0}, refine=lambda bpm: None)
    assert bpm == 130.0


def test_no_beat():
    assert choose_bpm({"multifeature": 0.0, "degara": 0.0, "percival": 0.0})[0] is None


# --- Key -------------------------------------------------------------------------------


def votes(edmm, check=None, others="7B"):
    result = {"edmm": edmm, "edmm@16384": check or edmm}
    for name in audio_analysis.KEY_CONFIRMING:
        result[name] = others
    return result


def test_relative_major_from_other_profiles_confirms_edmm():
    # Gold Dust: edmm hears D minor (7A), the others its relative F major (7B):
    # the same notes, so they confirm it; minor or major is edmm's call.
    key, sure, alternatives, note = choose_key(votes("7A", others="7B"))
    assert (key, sure, alternatives) == ("7A", True, [])
    assert note == "Key 7A, confirmed by 5 other methods"


def test_sure_key_has_no_alternatives():
    # Duck Sauce edit (2A): edmm, its check and braw agree; the rest hear 5B.
    result = votes("2A", others="5B") | {"braw": "2A"}
    assert choose_key(result)[:3] == ("2A", True, [])


def test_key_that_changes_with_detail_is_not_sure():
    key, sure, alternatives, _ = choose_key(votes("11A", check="9A", others="11B"))
    assert (key, sure, alternatives) == ("11A", False, ["9A"])


def test_key_no_other_profile_agrees():
    # DRZ - Dance is E-flat major (5B); edmm hears E-flat minor (2A), the others 5B.
    key, sure, alternatives, note = choose_key(votes("2A", others="5B"))
    assert (key, sure, alternatives) == ("2A", False, ["5B"])
    assert note == "Key 2A; other methods hear 5B"


def test_no_key():
    assert choose_key({"edmm": None})[0] is None


# --- Whole files -----------------------------------------------------------------------


@needs_ffmpeg
def test_drum_and_bass_loop():
    result = analyse(DNB_LOOP)
    assert result.error is None
    assert result.key == "7A" and result.key_sure
    # Heard at half time, like real drum & bass, and measured exactly; 174 stays as the
    # alternative until the genre or online sources decide.
    assert result.bpm == 87.0
    assert result.bpm_alternatives == [174.0]
    assert not result.bpm_sure
    assert result.version == audio_analysis.ANALYSIS_VERSION
    assert set(result.votes) == {"bpm", "key"}


@needs_ffmpeg
def test_too_short_file():
    result = analyse(FIXTURES / "untagged.mp3")  # half a second
    assert result.error == "Too short to analyse (under 10 seconds)"
    assert result.bpm is None and result.key is None


@needs_ffmpeg
def test_silent_file(tmp_path):
    path = tmp_path / "silence.flac"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "12",
         str(path)],
        check=True,
    )  # fmt: skip
    assert analyse(path).error == "The audio is silent"


@needs_ffmpeg
def test_broken_file(tmp_path):
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not audio at all" * 100)
    assert analyse(path).error.startswith("Can't read the audio")


@needs_ffmpeg
def test_command_line_compares_with_tags(tmp_path, capsys):
    audio_analysis.main(["--compare", str(DNB_LOOP)])
    out = json.loads(capsys.readouterr().out)
    assert out["key"] == "7A"
    # The loop has no tags to compare with.
    assert out["tags"] == {
        "bpm": None,
        "key": None,
        "bpm_matches": False,
        "bpm_in_alternatives": False,
        "key_matches": False,
    }

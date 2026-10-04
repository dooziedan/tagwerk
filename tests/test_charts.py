from app.charts import key_wheel
from app.keys import CAMELOT_CODES
from app.stats import KeyCell


def cells():
    return [KeyCell(code, code, 1, 1.0, 50) for code in CAMELOT_CODES]


def test_wheel_has_one_segment_per_key():
    assert len(key_wheel(cells())) == 24


def test_twelve_is_at_the_top_and_majors_outside():
    by_key = {seg.cell.camelot: seg for seg in key_wheel(cells())}
    assert by_key["12B"].x == 0 and by_key["12B"].y < by_key["12A"].y < 0  # straight up
    assert by_key["3B"].x > 0 and abs(by_key["3B"].y) < 0.01  # 3 o'clock
    assert by_key["6A"].y > 0  # bottom


def test_colours_are_plain_values_and_empty_keys_are_grey():
    cells = [KeyCell(code, code, 0 if code == "7A" else 3, 1.0, 50) for code in CAMELOT_CODES]
    by_key = {seg.cell.camelot: seg for seg in key_wheel(cells)}
    assert by_key["7A"].fill == "#9aa0a8"
    assert by_key["8A"].fill.startswith("hsl(") and "var(" not in by_key["8A"].fill
    assert by_key["8B"].fill != by_key["8A"].fill  # major stronger than minor

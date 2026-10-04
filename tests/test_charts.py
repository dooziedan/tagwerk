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

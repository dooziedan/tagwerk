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


def test_colours_are_plain_values_and_empty_keys_are_dark():
    cells = [KeyCell(code, code, 0 if code == "7A" else 3, 1.0, 50) for code in CAMELOT_CODES]
    by_key = {seg.cell.camelot: seg for seg in key_wheel(cells)}
    assert by_key["7A"].fill == "#1e1b4b"
    assert by_key["8A"].fill.startswith("hsl(") and "var(" not in by_key["8A"].fill
    assert by_key["8B"].fill != by_key["8A"].fill  # major stronger than minor


def _contrast(fill: str, text: str) -> float:
    import colorsys
    import re

    def luminance(rgb):
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in rgb]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    h, sat, light = (float(v) for v in re.findall(r"[\d.]+", fill))
    seg = colorsys.hls_to_rgb(h / 360, light / 100, sat / 100)
    txt = [int(text[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    hi, lo = sorted((luminance(seg), luminance(txt)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_standard_camelot_colours_with_readable_text():
    by_key = {seg.cell.camelot: seg for seg in key_wheel(cells())}
    assert by_key["1A"].fill.startswith("hsl(150,")  # aqua-green
    assert by_key["5B"].fill.startswith("hsl(30,")  # orange
    assert by_key["10B"].fill.startswith("hsl(240,")  # blue
    for code, seg in by_key.items():
        assert _contrast(seg.fill, seg.text) >= 4.5, code

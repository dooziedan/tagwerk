"""Percentages as shown on the pages.

Rounded, but never to 100 % while something is missing and never to 0 % while something is
there: 1,497 of 1,500 tracks with a tag is 99.8 %, shown as 99 % (not 100 %), and 1 of 1,500 is
shown as 1 % (or 0.1 % with one decimal), not 0 %.
"""


def shown(exact: float, digits: int = 0) -> float | int:
    """A percentage rounded to ``digits`` decimals, kept off 0 and 100 unless it's exact."""
    step = 10**-digits
    value = round(exact, digits)
    if value >= 100 and exact < 100:
        value = 100 - step
    elif value <= 0 and exact > 0:
        value = step
    return int(value) if digits == 0 else round(value, digits)


def percent(part: float, whole: float, digits: int = 0) -> float | int:
    """``part`` of ``whole`` in percent, as shown (0 when ``whole`` is 0)."""
    return shown(100 * part / whole, digits) if whole else 0

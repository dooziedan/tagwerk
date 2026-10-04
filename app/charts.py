"""Geometry and colours for charts drawn as inline SVG (no JavaScript chart library needed).

Colours are written straight into the SVG as attributes, so the chart looks the same in
every browser, without relying on newer CSS features.
"""

import math
from dataclasses import dataclass

from app.stats import KeyCell

# Camelot wheel layout, in SVG units (viewBox is -100..100).
OUTER = (98, 67)  # major keys (B): outer radius, inner radius
INNER = (65, 34)  # minor keys (A)
SEGMENT = 30  # degrees per key number
GAP = 1.2  # degrees left empty between segments, so they read as separate tiles
TEXT = "#1b1d22"  # dark text: readable on every segment colour, in light and dark mode


@dataclass
class WheelSegment:
    cell: KeyCell
    path: str  # SVG path of the ring segment
    x: float  # label position
    y: float
    fill: str  # colour of the segment
    text: str  # colour of its labels


def camelot_colour(number: int, letter: str, count: int) -> tuple[str, str]:
    """Segment and text colour. Each number has its own hue going round the wheel, like the
    well-known Camelot wheel; major (B) is stronger than minor (A). Empty keys are grey."""
    if count == 0:
        return "#9aa0a8", TEXT  # grey, same dark text
    hue = (165 + (number - 1) * 30) % 360
    lightness = 66 if letter == "B" else 80
    return f"hsl({hue}, 62%, {lightness}%)", TEXT


def key_wheel(cells: list[KeyCell]) -> list[WheelSegment]:
    """Place the 24 key cells on a Camelot wheel: 12 at the top, clockwise like a clock.

    Minor keys (A) form the inner ring, major keys (B) the outer ring, so harmonic
    neighbours (same number, or one step around) are next to each other.
    """
    segments = []
    for cell in cells:
        number, letter = int(cell.camelot[:-1]), cell.camelot[-1]
        outer, inner = OUTER if letter == "B" else INNER
        centre = number * SEGMENT  # degrees clockwise from 12 o'clock
        start, end = centre - SEGMENT / 2 + GAP / 2, centre + SEGMENT / 2 - GAP / 2
        x, y = _point((outer + inner) / 2, centre)
        fill, text = camelot_colour(number, letter, cell.count)
        segments.append(
            WheelSegment(
                cell, _ring_segment(outer - 0.6, inner + 0.6, start, end), x, y, fill, text
            )
        )
    return segments


def _point(radius: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees - 90)  # 0° = 12 o'clock
    return round(radius * math.cos(angle), 2), round(radius * math.sin(angle), 2)


def _ring_segment(outer: float, inner: float, start: float, end: float) -> str:
    x1, y1 = _point(outer, start)
    x2, y2 = _point(outer, end)
    x3, y3 = _point(inner, end)
    x4, y4 = _point(inner, start)
    return (
        f"M{x1},{y1} A{outer},{outer} 0 0 1 {x2},{y2} L{x3},{y3} A{inner},{inner} 0 0 0 {x4},{y4} Z"
    )

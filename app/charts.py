"""Geometry for charts drawn as inline SVG (no JavaScript chart library needed)."""

import math
from dataclasses import dataclass

from app.stats import KeyCell

# Camelot wheel layout, in SVG units (viewBox is -100..100).
OUTER = (97, 66)  # major keys (B): outer radius, inner radius
INNER = (64, 33)  # minor keys (A)
SEGMENT = 30  # degrees per key number


@dataclass
class WheelSegment:
    cell: KeyCell
    path: str  # SVG path of the ring segment
    x: float  # label position
    y: float


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
        start, end = centre - SEGMENT / 2, centre + SEGMENT / 2
        label_radius = (outer + inner) / 2
        x, y = _point(label_radius, centre)
        segments.append(WheelSegment(cell, _ring_segment(outer, inner, start, end), x, y))
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

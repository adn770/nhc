"""SVG rendering of Building exterior walls.

Implements the 3-strip-polygon brick rendering described in
``design/building_generator.md`` section 7.1. A wall run is a
straight orthogonal segment of a Building's perimeter; each run is
drawn as three stacked courses of bricks with staggered offsets,
random widths, and a small probability of missing bricks.

Tunable constants live at module top-level (see design doc section
7.5). The stone variant lands in a later milestone alongside its
own constants.
"""

from __future__ import annotations

import random

from nhc.rendering._svg_helpers import BG

# ── Brick rendering constants (initial values, tunable) ───────────

BRICK_FILL = "#B4695A"
BRICK_SEAM = "#6A3A2A"
BRICK_MISSING = BG

BRICK_STRIP_COUNT = 3                 # 3 running-bond courses per run
BRICK_SEAM_WIDTH = 1.0                # px
BRICK_MEAN_WIDTH = 12.0               # px
BRICK_WIDTH_JITTER = 0.25             # +/- fraction of mean
BRICK_MISSING_PROBABILITY = 0.05      # ~5% bricks missing per strip
BRICK_WALL_THICKNESS = 8.0            # total band thickness in px

# Per-strip offset for the first seam; distinct values give the
# running-bond look.
_BRICK_STRIP_OFFSETS = (
    0.0,
    BRICK_MEAN_WIDTH / 2,
    -BRICK_MEAN_WIDTH / 4,
)


def render_brick_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    thickness: float = BRICK_WALL_THICKNESS,
    *, seed: int = 0,
) -> list[str]:
    """Render a straight orthogonal wall run as brick.

    Endpoints are pixel coordinates of the wall centerline; the run
    must be strictly horizontal (``y0 == y1``) or vertical
    (``x0 == x1``). Oblique runs raise ``ValueError``.

    The band is ``thickness`` px wide, split evenly among
    :data:`BRICK_STRIP_COUNT` courses stacked perpendicular to the
    run direction. Each course is one ``<rect>`` filled with
    :data:`BRICK_FILL`, followed by per-brick seam ``<line>``
    elements and per-brick ``<rect>`` overlays that paint missing
    bricks with the page background colour.

    Output is deterministic given the same ``seed`` + endpoints.
    """
    if x0 == x1 and y0 == y1:
        return []
    horizontal = y0 == y1
    vertical = x0 == x1
    if not (horizontal ^ vertical):
        raise ValueError(
            "wall run must be strictly horizontal or vertical"
        )

    run_len = abs(x1 - x0) if horizontal else abs(y1 - y0)
    run_start = min(x0, x1) if horizontal else min(y0, y1)
    perp_start = (y0 if horizontal else x0) - thickness / 2
    strip_thick = thickness / BRICK_STRIP_COUNT

    rng = random.Random(seed)
    out: list[str] = []
    for idx in range(BRICK_STRIP_COUNT):
        perp = perp_start + idx * strip_thick
        out.append(_strip_background(
            horizontal, run_start, perp, run_len, strip_thick,
        ))

        # Compute seam positions along the run for this strip.
        edges: list[float] = []
        pos = _BRICK_STRIP_OFFSETS[idx]
        while pos < run_len:
            if pos > 0:
                edges.append(pos)
            jitter = 1.0 + rng.uniform(
                -BRICK_WIDTH_JITTER, BRICK_WIDTH_JITTER,
            )
            pos += BRICK_MEAN_WIDTH * jitter

        for edge in edges:
            out.append(_seam_line(
                horizontal, run_start, perp, edge, strip_thick,
            ))

        # Missing-brick overlays between consecutive edges.
        all_edges = [0.0] + edges + [run_len]
        for i in range(len(all_edges) - 1):
            left = all_edges[i]
            right = all_edges[i + 1]
            if rng.random() < BRICK_MISSING_PROBABILITY:
                out.append(_missing_brick(
                    horizontal, run_start, perp,
                    left, right, strip_thick,
                ))
    return out


def _strip_background(
    horizontal: bool, run_start: float, perp: float,
    run_len: float, strip_thick: float,
) -> str:
    if horizontal:
        return (
            f'<rect x="{run_start:.1f}" y="{perp:.1f}" '
            f'width="{run_len:.1f}" height="{strip_thick:.1f}" '
            f'fill="{BRICK_FILL}"/>'
        )
    return (
        f'<rect x="{perp:.1f}" y="{run_start:.1f}" '
        f'width="{strip_thick:.1f}" height="{run_len:.1f}" '
        f'fill="{BRICK_FILL}"/>'
    )


def _seam_line(
    horizontal: bool, run_start: float, perp: float,
    edge: float, strip_thick: float,
) -> str:
    if horizontal:
        sx = run_start + edge
        return (
            f'<line x1="{sx:.1f}" y1="{perp:.1f}" '
            f'x2="{sx:.1f}" y2="{perp + strip_thick:.1f}" '
            f'stroke="{BRICK_SEAM}" '
            f'stroke-width="{BRICK_SEAM_WIDTH}"/>'
        )
    sy = run_start + edge
    return (
        f'<line x1="{perp:.1f}" y1="{sy:.1f}" '
        f'x2="{perp + strip_thick:.1f}" y2="{sy:.1f}" '
        f'stroke="{BRICK_SEAM}" '
        f'stroke-width="{BRICK_SEAM_WIDTH}"/>'
    )


def _missing_brick(
    horizontal: bool, run_start: float, perp: float,
    left: float, right: float, strip_thick: float,
) -> str:
    width = right - left
    if horizontal:
        return (
            f'<rect x="{run_start + left:.1f}" y="{perp:.1f}" '
            f'width="{width:.1f}" height="{strip_thick:.1f}" '
            f'fill="{BRICK_MISSING}"/>'
        )
    return (
        f'<rect x="{perp:.1f}" y="{run_start + left:.1f}" '
        f'width="{strip_thick:.1f}" height="{width:.1f}" '
        f'fill="{BRICK_MISSING}"/>'
    )

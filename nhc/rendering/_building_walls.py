"""SVG rendering of Building exterior walls.

Brick and stone share one implementation: each wall run is drawn
as a two-course running-bond chain of rounded ``<rect>`` elements
whose widths stay within a tight jitter band so units read as
regularly sized. Brick and stone differ only in fill and stroke
colour.

See ``design/building_generator.md`` section 7.
"""

from __future__ import annotations

import random


# ── Shared masonry constants (initial values, tunable) ────────

MASONRY_STRIP_COUNT = 2               # two running-bond courses
MASONRY_MEAN_WIDTH = 12.0             # unit length along the run (px)
MASONRY_WIDTH_LOW = 0.9               # min multiplier for mean
MASONRY_WIDTH_HIGH = 1.1              # max multiplier (±10% regular)
MASONRY_CORNER_RADIUS = 1.2           # rounded rect rx / ry
MASONRY_STROKE_WIDTH = 1.0            # unit rect stroke thickness
MASONRY_WALL_THICKNESS = 8.0          # total band thickness (px)

# Per-strip running-bond offset -- strip 1 starts half a mean-unit
# further along the run than strip 0.
_MASONRY_STRIP_OFFSETS = (0.0, MASONRY_MEAN_WIDTH / 2)


# ── Material palette ─────────────────────────────────────────

BRICK_FILL = "#B4695A"
BRICK_SEAM = "#6A3A2A"

STONE_FILL = "#9A8E80"
STONE_SEAM = "#4A3E35"


def render_brick_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    thickness: float = MASONRY_WALL_THICKNESS,
    *, seed: int = 0,
) -> list[str]:
    """Render a straight orthogonal wall run as brick masonry."""
    return _render_masonry_wall_run(
        x0, y0, x1, y1, thickness,
        seed=seed, fill=BRICK_FILL, stroke=BRICK_SEAM,
    )


def render_stone_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    thickness: float = MASONRY_WALL_THICKNESS,
    *, seed: int = 0,
) -> list[str]:
    """Render a straight orthogonal wall run as stone masonry."""
    return _render_masonry_wall_run(
        x0, y0, x1, y1, thickness,
        seed=seed, fill=STONE_FILL, stroke=STONE_SEAM,
    )


def _render_masonry_wall_run(
    x0: float, y0: float, x1: float, y1: float,
    thickness: float, *, seed: int, fill: str, stroke: str,
) -> list[str]:
    """Shared implementation: 2-strip rounded-rect chain.

    Endpoints are pixel coordinates of the wall centerline; the
    run must be strictly horizontal (``y0 == y1``) or vertical
    (``x0 == x1``). Oblique runs raise ``ValueError``. Every unit
    is a rounded ``<rect>`` filled with ``fill`` and stroked with
    ``stroke`` at :data:`MASONRY_STROKE_WIDTH`. Widths jitter in
    ``[MASONRY_WIDTH_LOW, MASONRY_WIDTH_HIGH]`` around
    :data:`MASONRY_MEAN_WIDTH`, clipped at the run end so no unit
    overflows. Output is deterministic given the same ``seed`` +
    endpoints.
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
    strip_thick = thickness / MASONRY_STRIP_COUNT

    rng = random.Random(seed)
    out: list[str] = []
    for idx in range(MASONRY_STRIP_COUNT):
        perp = perp_start + idx * strip_thick
        pos = max(0.0, _MASONRY_STRIP_OFFSETS[idx])
        while pos < run_len:
            width = MASONRY_MEAN_WIDTH * rng.uniform(
                MASONRY_WIDTH_LOW, MASONRY_WIDTH_HIGH,
            )
            width = min(width, run_len - pos)
            out.append(_masonry_rect(
                horizontal, run_start, perp,
                pos, width, strip_thick, fill, stroke,
            ))
            pos += width
    return out


def _masonry_rect(
    horizontal: bool, run_start: float, perp: float,
    pos: float, width: float, strip_thick: float,
    fill: str, stroke: str,
) -> str:
    if horizontal:
        x = run_start + pos
        y = perp
        w = width
        h = strip_thick
    else:
        x = perp
        y = run_start + pos
        w = strip_thick
        h = width
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" '
        f'width="{w:.1f}" height="{h:.1f}" '
        f'rx="{MASONRY_CORNER_RADIUS}" '
        f'ry="{MASONRY_CORNER_RADIUS}" '
        f'fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{MASONRY_STROKE_WIDTH}"/>'
    )

"""Composite SVG renderer for a Building floor.

Stitches the base dungeon floor SVG with per-run brick or stone
wall overlays along the Building's exterior perimeter. Circular
and octagonal footprints fall back to the base SVG because the
M4 / M5 wall renderers only handle orthogonal runs.

See ``design/building_generator.md`` sections 4 and 7.
"""

from __future__ import annotations

from nhc.dungeon.building import Building
from nhc.dungeon.model import LShape, RectShape, Rect
from nhc.rendering._building_walls import (
    render_brick_wall_run,
    render_stone_wall_run,
)
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.svg import render_floor_svg


def render_building_floor_svg(
    building: Building, floor_index: int, seed: int = 0,
) -> str:
    """Render one Building floor as a composite SVG string.

    Draws the interior (floor / walls / detail) through the
    existing :func:`render_floor_svg`, then overlays brick or
    stone runs along the exterior perimeter depending on
    ``building.wall_material``.
    """
    if not 0 <= floor_index < len(building.floors):
        raise IndexError(
            f"floor_index {floor_index} out of range "
            f"[0, {len(building.floors)})"
        )
    level = building.floors[floor_index]
    base = render_floor_svg(level, seed=seed)
    if building.wall_material == "dungeon":
        return base
    polygon = _perimeter_polygon(building)
    if polygon is None:
        return base

    run_renderer = (
        render_brick_wall_run
        if building.wall_material == "brick"
        else render_stone_wall_run
    )

    fragments: list[str] = []
    n = len(polygon)
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        fragments.extend(run_renderer(
            ax, ay, bx, by, seed=seed + i,
        ))
    if not fragments:
        return base
    inject = "".join(fragments)
    return base.replace("</svg>", f"{inject}</svg>")


def _perimeter_polygon(
    building: Building,
) -> list[tuple[float, float]] | None:
    """Pixel-coord perimeter polygon for orthogonal base shapes.

    Returns ``None`` for circular / octagonal footprints so the
    caller can fall back to the base SVG.
    """
    shape = building.base_shape
    rect = building.base_rect
    if isinstance(shape, RectShape):
        return _rect_polygon(rect)
    if isinstance(shape, LShape):
        return _lshape_polygon(rect, shape)
    return None


def _rect_polygon(rect: Rect) -> list[tuple[float, float]]:
    x0 = PADDING + rect.x * CELL
    y0 = PADDING + rect.y * CELL
    x1 = PADDING + rect.x2 * CELL
    y1 = PADDING + rect.y2 * CELL
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _lshape_polygon(
    rect: Rect, shape: LShape,
) -> list[tuple[float, float]]:
    """Build a 6-corner outline for an L-shape footprint.

    The notch is always in one of the four rect corners; the
    6-vertex polygon walks around the resulting L in clockwise
    order starting at the top-left of the remaining floor area.
    """
    notch = shape._notch_rect(rect)
    x0 = rect.x
    y0 = rect.y
    x1 = rect.x2
    y1 = rect.y2
    nx0 = notch.x
    ny0 = notch.y
    nx1 = notch.x2
    ny1 = notch.y2

    def _p(tx: float, ty: float) -> tuple[float, float]:
        return (PADDING + tx * CELL, PADDING + ty * CELL)

    if shape.corner == "nw":
        return [
            _p(nx1, y0), _p(x1, y0),
            _p(x1, y1), _p(x0, y1),
            _p(x0, ny1), _p(nx1, ny1),
        ]
    if shape.corner == "ne":
        return [
            _p(x0, y0), _p(nx0, y0),
            _p(nx0, ny1), _p(x1, ny1),
            _p(x1, y1), _p(x0, y1),
        ]
    if shape.corner == "sw":
        return [
            _p(x0, y0), _p(x1, y0),
            _p(x1, y1), _p(nx1, y1),
            _p(nx1, ny0), _p(x0, ny0),
        ]
    # "se"
    return [
        _p(x0, y0), _p(x1, y0),
        _p(x1, ny0), _p(nx0, ny0),
        _p(nx0, y1), _p(x0, y1),
    ]

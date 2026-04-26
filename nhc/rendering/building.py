"""Composite SVG renderer for a Building floor.

Stitches the base dungeon floor SVG with per-run brick or stone
wall overlays along the Building's exterior perimeter. Circular
and octagonal footprints fall back to the base SVG because the
M4 / M5 wall renderers only handle orthogonal runs.

See ``design/building_generator.md`` sections 4 and 7.
"""

from __future__ import annotations

import math

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    CircleShape, Level, LShape, OctagonShape, Rect, RectShape,
    canonicalize,
)
from nhc.rendering._building_walls import (
    MASONRY_WALL_THICKNESS,
    render_brick_wall_run,
    render_stone_wall_run,
)
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.svg import render_floor_svg


# Interior wall stroke colors, keyed by Building.interior_wall_material.
# See design/building_interiors.md — interior walls read as simple
# wood/stone/brick lines, distinct from the stylized perimeter pass.
INTERIOR_WALL_COLORS: dict[str, str] = {
    "wood":  "#7a4e2c",
    "stone": "#707070",
    "brick": "#c4651d",
}
_INTERIOR_WALL_STROKE = CELL * 0.25

# Circle perimeter is approximated as an N-sided polygon. The
# segment count scales with circumference so each edge stays
# roughly the same pixel length across tower sizes.
_CIRCLE_TARGET_SEGMENT_PX = 24.0
_CIRCLE_MIN_SEGMENTS = 12
_CIRCLE_MAX_SEGMENTS = 36


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
    footprint = building.base_shape.floor_tiles(building.base_rect)
    # render_floor_svg lays its content inside a
    # <g transform="translate(PADDING, PADDING)">; pass the outer
    # building polygon in level-local pixel coords (PADDING
    # subtracted) so the wood-floor clip doesn't double the
    # offset.
    perimeter = _perimeter_polygon(building)
    if perimeter is not None:
        polygon = [(x - PADDING, y - PADDING) for x, y in perimeter]
    else:
        polygon = None
    base = render_floor_svg(
        level, seed=seed,
        building_footprint=footprint,
        building_polygon=polygon,
    )
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

    # Interior partitions render BEFORE the exterior masonry so
    # the curved / clipped exterior wall overlays any partition
    # extension into the rim zone (cleaning up the T-junction
    # visually for circle / octagon footprints).
    fragments: list[str] = []
    interior_frags = _render_interior_walls(level, building)
    if interior_frags:
        fragments.extend(interior_frags)

    n = len(polygon)
    # Extend each edge by half the wall thickness at both ends so
    # adjacent edges overlap at every polygon vertex. This paints
    # the thick x thick corner square fully -- without it, each
    # wall stops at the vertex and the corner square is only half
    # covered, leaving a visible gap on the outside of every
    # corner.
    ext = MASONRY_WALL_THICKNESS / 2
    for i in range(n):
        ax, ay = polygon[i]
        bx, by = polygon[(i + 1) % n]
        dx = bx - ax
        dy = by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        ux = dx / length
        uy = dy / length
        ax_ext = ax - ux * ext
        ay_ext = ay - uy * ext
        bx_ext = bx + ux * ext
        by_ext = by + uy * ext
        fragments.extend(run_renderer(
            ax_ext, ay_ext, bx_ext, by_ext, seed=seed + i,
        ))
    if not fragments:
        return base
    inject = "".join(fragments)
    return base.replace("</svg>", f"{inject}</svg>")


_DOOR_SUPPRESSING_FEATURES = frozenset({
    "door_open", "door_closed", "door_locked",
})


def _render_interior_walls(
    level: Level, building: Building,
) -> list[str]:
    """Emit one ``<line>`` per coalesced run of interior edges.

    See ``design/building_interiors.md`` — partitioners emit
    canonical axis-aligned edges on ``Level.interior_edges``. This
    pass draws them directly; door-suppressed edges (a door tile
    adjacent with a matching ``door_side``) are skipped so the
    door glyph replaces the wall stroke visually. Secret doors do
    NOT suppress the edge — they deliberately read as wall until
    discovered.
    """
    if not level.interior_edges:
        return []

    # Split edges by side and filter out door-suppressed ones.
    norths: set[tuple[int, int]] = set()
    wests: set[tuple[int, int]] = set()
    for (x, y, side) in level.interior_edges:
        if _edge_has_visible_door(level, x, y, side):
            continue
        if side == "north":
            norths.add((x, y))
        elif side == "west":
            wests.add((x, y))

    color = INTERIOR_WALL_COLORS.get(
        building.interior_wall_material,
        INTERIOR_WALL_COLORS["stone"],
    )

    fragments: list[str] = []
    for (ax, ay, bx, by) in _coalesce_north_edges(norths):
        fragments.append(_edge_line(ax, ay, bx, by, color))
    for (ax, ay, bx, by) in _coalesce_west_edges(wests):
        fragments.append(_edge_line(ax, ay, bx, by, color))
    return fragments


def _edge_has_visible_door(
    level: Level, edge_x: int, edge_y: int, edge_side: str,
) -> bool:
    """True when an open/closed/locked door on either adjacent
    tile targets this canonical edge. The door glyph substitutes
    for the wall line."""
    if edge_side == "north":
        candidates = [(edge_x, edge_y - 1), (edge_x, edge_y)]
    elif edge_side == "west":
        candidates = [(edge_x - 1, edge_y), (edge_x, edge_y)]
    else:
        return False
    for (tx, ty) in candidates:
        tile = level.tile_at(tx, ty)
        if tile is None:
            continue
        if tile.feature not in _DOOR_SUPPRESSING_FEATURES:
            continue
        if not tile.door_side:
            continue
        target = canonicalize(tx, ty, tile.door_side)
        if target == (edge_x, edge_y, edge_side):
            return True
    return False


def _coalesce_north_edges(
    norths: set[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge consecutive north edges at the same y into one span."""
    runs: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for (x, y) in sorted(norths):
        if (x, y) in seen:
            continue
        end = x
        while (end + 1, y) in norths:
            end += 1
        for ix in range(x, end + 1):
            seen.add((ix, y))
        # Line from pixel (x, y) to (end+1, y) — a horizontal line
        # at y spanning that many tile columns.
        runs.append((x, y, end + 1, y))
    return runs


def _coalesce_west_edges(
    wests: set[tuple[int, int]],
) -> list[tuple[int, int, int, int]]:
    """Merge consecutive west edges at the same x into one span."""
    runs: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for (x, y) in sorted(wests):
        if (x, y) in seen:
            continue
        end = y
        while (x, end + 1) in wests:
            end += 1
        for iy in range(y, end + 1):
            seen.add((x, iy))
        runs.append((x, y, x, end + 1))
    return runs


def _edge_line(
    ax: int, ay: int, bx: int, by: int, color: str,
) -> str:
    """SVG ``<line>`` on tile-boundary coordinates (not centres)."""
    px0 = PADDING + ax * CELL
    py0 = PADDING + ay * CELL
    px1 = PADDING + bx * CELL
    py1 = PADDING + by * CELL
    return (
        f'<line x1="{px0}" y1="{py0}" x2="{px1}" y2="{py1}" '
        f'stroke="{color}" stroke-width="{_INTERIOR_WALL_STROKE}" '
        f'stroke-linecap="round"/>'
    )


def _perimeter_polygon(
    building: Building,
) -> list[tuple[float, float]] | None:
    """Pixel-coord perimeter polygon for every base shape except
    cave-style ones. Diagonal edges (octagon sides, circle
    approximation) are handled by the masonry renderer via
    per-rect rotation transforms."""
    shape = building.base_shape
    rect = building.base_rect
    if isinstance(shape, RectShape):
        return _rect_polygon(rect)
    if isinstance(shape, LShape):
        return _lshape_polygon(rect, shape)
    if isinstance(shape, OctagonShape):
        return _octagon_polygon(rect)
    if isinstance(shape, CircleShape):
        return _circle_polygon(rect, shape)
    return None


def _rect_polygon(rect: Rect) -> list[tuple[float, float]]:
    x0 = PADDING + rect.x * CELL
    y0 = PADDING + rect.y * CELL
    x1 = PADDING + rect.x2 * CELL
    y1 = PADDING + rect.y2 * CELL
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _octagon_polygon(rect: Rect) -> list[tuple[float, float]]:
    """Eight-vertex polygon matching OctagonShape.floor_tiles.

    The flat sides are on N/E/S/W axis-aligned; the four 45-degree
    chamfered corners become diagonal wall runs.
    """
    clip = max(1, min(rect.width, rect.height) // 3)

    def _p(tx: int, ty: int) -> tuple[float, float]:
        return (PADDING + tx * CELL, PADDING + ty * CELL)

    return [
        _p(rect.x + clip, rect.y),
        _p(rect.x2 - clip, rect.y),
        _p(rect.x2, rect.y + clip),
        _p(rect.x2, rect.y2 - clip),
        _p(rect.x2 - clip, rect.y2),
        _p(rect.x + clip, rect.y2),
        _p(rect.x, rect.y2 - clip),
        _p(rect.x, rect.y + clip),
    ]


def _circle_polygon(
    rect: Rect, shape: CircleShape,
) -> list[tuple[float, float]]:
    """Regular N-gon approximating CircleShape.floor_tiles.

    Segment count scales with circumference so each edge stays
    roughly ``_CIRCLE_TARGET_SEGMENT_PX`` long.
    """
    diameter = shape._diameter(rect)
    radius_px = diameter * CELL / 2.0
    cx = PADDING + (rect.x + rect.width / 2.0) * CELL
    cy = PADDING + (rect.y + rect.height / 2.0) * CELL
    circumference = 2.0 * math.pi * radius_px
    n = max(
        _CIRCLE_MIN_SEGMENTS,
        min(
            _CIRCLE_MAX_SEGMENTS,
            int(circumference / _CIRCLE_TARGET_SEGMENT_PX),
        ),
    )
    return [
        (
            cx + radius_px * math.cos(2 * math.pi * i / n),
            cy + radius_px * math.sin(2 * math.pi * i / n),
        )
        for i in range(n)
    ]


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

"""Dungeon polygon construction and section partitioning."""

from __future__ import annotations

import math
import random
import re

from shapely.geometry import Polygon
from shapely.ops import unary_union

from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level, LShape,
    OctagonShape, PillShape, RectShape, TempleShape,
)
from nhc.rendering._svg_helpers import CELL


def _room_shapely_polygon(room) -> Polygon | None:
    """Build a Shapely polygon from a room's smooth outline.

    Approximates circles and arcs with 64-segment polylines.
    Returns None for rect rooms (use tile rects instead).
    """
    from nhc.rendering.svg import (
        _cave_svg_outline,
        _hybrid_svg_outline,
        _polygon_vertices,
    )

    shape = room.shape
    r = room.rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if isinstance(shape, CircleShape):
        d = shape._diameter(r)
        radius = d * CELL / 2
        cx = px + pw / 2
        cy = py + ph / 2
        n = 64
        return Polygon([
            (cx + radius * math.cos(2 * math.pi * i / n),
             cy + radius * math.sin(2 * math.pi * i / n))
            for i in range(n)
        ])

    if isinstance(shape, RectShape):
        return Polygon([
            (px, py), (px + pw, py),
            (px + pw, py + ph), (px, py + ph),
        ])

    if isinstance(shape, LShape):
        notch = shape._notch_rect(r)
        x0, y0 = r.x, r.y
        x1, y1 = r.x2, r.y2
        nx0, ny0 = notch.x, notch.y
        nx1, ny1 = notch.x2, notch.y2

        def _tp(tx: int, ty: int) -> tuple[float, float]:
            return (tx * CELL, ty * CELL)

        if shape.corner == "nw":
            verts = [
                _tp(nx1, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(x0, y1),
                _tp(x0, ny1), _tp(nx1, ny1),
            ]
        elif shape.corner == "ne":
            verts = [
                _tp(x0, y0), _tp(nx0, y0),
                _tp(nx0, ny1), _tp(x1, ny1),
                _tp(x1, y1), _tp(x0, y1),
            ]
        elif shape.corner == "sw":
            verts = [
                _tp(x0, y0), _tp(x1, y0),
                _tp(x1, y1), _tp(nx1, y1),
                _tp(nx1, ny0), _tp(x0, ny0),
            ]
        else:  # "se"
            verts = [
                _tp(x0, y0), _tp(x1, y0),
                _tp(x1, ny0), _tp(nx0, ny0),
                _tp(nx0, y1), _tp(x0, y1),
            ]
        return Polygon(verts)

    if isinstance(
        shape, (OctagonShape, CrossShape, PillShape, TempleShape),
    ):
        verts = _polygon_vertices(shape, r)
        if verts:
            return Polygon(verts)
        return None

    if isinstance(shape, HybridShape):
        outline = _hybrid_svg_outline(room)
        if not outline:
            return None
        return _svg_path_to_polygon(outline)

    if isinstance(shape, CaveShape):
        outline = _cave_svg_outline(room)
        if not outline:
            return None
        return _svg_path_to_polygon(outline)

    return None


def _svg_path_to_polygon(svg_el: str) -> Polygon | None:
    """Convert an SVG path/polygon element to a Shapely Polygon.

    Handles M, L, A, and Z commands. Arcs are approximated with
    line segments.
    """
    # Extract points from <polygon points="...">
    poly_match = re.search(r'<polygon points="([^"]+)"', svg_el)
    if poly_match:
        pts = []
        for pt in poly_match.group(1).split():
            x, y = pt.split(",")
            pts.append((float(x), float(y)))
        if len(pts) >= 3:
            return Polygon(pts)
        return None

    # Extract d="..." from <path>
    path_match = re.search(r'd="([^"]+)"', svg_el)
    if not path_match:
        return None
    d = path_match.group(1)

    # Tokenize: split on command letters, keeping the letter
    tokens = re.findall(r'[MLAHVCZ][^MLAHVCZ]*', d.strip())
    pts: list[tuple[float, float]] = []
    cx, cy = 0.0, 0.0

    for tok in tokens:
        cmd = tok[0]
        args = [float(v) for v in re.findall(r'-?[\d.]+', tok)]
        if cmd == 'M':
            cx, cy = args[0], args[1]
            pts.append((cx, cy))
        elif cmd == 'L':
            cx, cy = args[0], args[1]
            pts.append((cx, cy))
        elif cmd == 'H':
            cx = args[0]
            pts.append((cx, cy))
        elif cmd == 'V':
            cy = args[0]
            pts.append((cx, cy))
        elif cmd == 'A':
            # A rx ry x-rot large-arc sweep ex ey
            rx, ry = args[0], args[1]
            large = int(args[3])
            sweep = int(args[4])
            ex, ey = args[5], args[6]
            # Approximate arc with line segments
            arc_pts = _approximate_arc(
                cx, cy, rx, ry, large, sweep, ex, ey)
            pts.extend(arc_pts)
            cx, cy = ex, ey
        elif cmd == 'C':
            # C c1x,c1y c2x,c2y ex,ey — cubic bezier
            # Approximate with 8 line segments
            c1x, c1y = args[0], args[1]
            c2x, c2y = args[2], args[3]
            ex, ey = args[4], args[5]
            for i in range(1, 9):
                t = i / 8
                u = 1 - t
                bx = (u**3 * cx + 3 * u**2 * t * c1x
                      + 3 * u * t**2 * c2x + t**3 * ex)
                by = (u**3 * cy + 3 * u**2 * t * c1y
                      + 3 * u * t**2 * c2y + t**3 * ey)
                pts.append((bx, by))
            cx, cy = ex, ey
        elif cmd == 'Z':
            pass  # close path

    if len(pts) >= 3:
        return Polygon(pts)
    return None


def _approximate_arc(
    sx: float, sy: float,
    rx: float, ry: float,
    large: int, sweep: int,
    ex: float, ey: float,
    n_seg: int = 32,
) -> list[tuple[float, float]]:
    """Approximate an SVG arc with line segments.

    Uses the SVG arc parameterization to find center, then
    samples n_seg points along the arc.
    """
    # Midpoint
    mx, my = (sx + ex) / 2, (sy + ey) / 2
    dx, dy = (sx - ex) / 2, (sy - ey) / 2

    # Compute center (simplified for rx==ry circular arcs)
    r = rx
    d_sq = dx * dx + dy * dy
    if d_sq > r * r:
        return [(ex, ey)]
    if d_sq < 1e-9:
        return [(ex, ey)]
    sq = math.sqrt(max(0.0, (r * r - d_sq) / d_sq))
    if large != sweep:
        ccx = mx + sq * dy
        ccy = my - sq * dx
    else:
        ccx = mx - sq * dy
        ccy = my + sq * dx

    # Start and end angles
    a_start = math.atan2(sy - ccy, sx - ccx)
    a_end = math.atan2(ey - ccy, ex - ccx)

    # Determine sweep direction
    if sweep == 1:
        da = a_end - a_start
        if da <= 0:
            da += 2 * math.pi
    else:
        da = a_end - a_start
        if da >= 0:
            da -= 2 * math.pi

    pts = []
    for i in range(1, n_seg + 1):
        t = i / n_seg
        a = a_start + da * t
        pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def _build_dungeon_polygon(
    level: Level,
    cave_wall_poly=None,
    cave_tiles: set[tuple[int, int]] | None = None,
) -> Polygon:
    """Build a Shapely polygon covering room interiors only.

    Uses _room_shapely_polygon for every room (rect, circle,
    octagon, cross, hybrid) so the clip boundary follows the
    wall path.  Corridors are normally excluded — they are
    handled separately by grid/detail rendering.

    For cave regions, the precomputed *cave_wall_poly* (the
    jittered wall polygon built by :func:`_build_cave_wall_geometry`)
    replaces the per-room cave outlines AND pulls in the connected
    corridor tiles, so the dungeon clip extends out to exactly the
    curve the wall stroke follows.  This keeps the grid and floor
    fill aligned with the wall — same strategy used for circular
    rooms, where the circle polygon serves as both fill and clip.
    """
    cave_tiles = cave_tiles or set()
    polys = []

    for room in level.rooms:
        if (cave_wall_poly is not None
                and isinstance(room.shape, CaveShape)
                and room.floor_tiles() & cave_tiles):
            continue
        room_poly = _room_shapely_polygon(room)
        if room_poly and not room_poly.is_empty:
            polys.append(room_poly)

    if cave_wall_poly is not None and not cave_wall_poly.is_empty:
        polys.append(cave_wall_poly)

    if not polys:
        return Polygon()
    return unary_union(polys)


def _pick_section_points(
    corners: list[tuple[float, float]],
    anchor: tuple[float, float],
    grid_size: float,
    rng: random.Random | None = None,
) -> list[tuple[float, float]]:
    """Pick 3 random perimeter points and sort by angle from anchor."""
    rng = rng or random.Random()

    def _random_perimeter_point(edge: int) -> tuple[float, float]:
        t = rng.uniform(0, grid_size)
        if edge == 0:
            return (corners[0][0] + t, corners[0][1])
        if edge == 1:
            return (corners[1][0], corners[1][1] + t)
        if edge == 2:
            return (corners[2][0] - t, corners[2][1])
        return (corners[3][0], corners[3][1] - t)

    edges = [rng.randint(0, 3) for _ in range(3)]
    pts = [_random_perimeter_point(e) for e in edges]
    pts.sort(key=lambda p: math.atan2(
        p[1] - anchor[1], p[0] - anchor[0]))
    return pts


def _get_edge_index(
    p: tuple[float, float],
    corners: list[tuple[float, float]],
    grid_size: float,
) -> int:
    gx_px = corners[0][0]
    gy_px = corners[0][1]
    if abs(p[1] - gy_px) < 1e-3:
        return 0
    if abs(p[0] - (gx_px + grid_size)) < 1e-3:
        return 1
    if abs(p[1] - (gy_px + grid_size)) < 1e-3:
        return 2
    return 3


def _build_sections(
    anchor: tuple[float, float],
    pts: list[tuple[float, float]],
    corners: list[tuple[float, float]],
) -> list[Polygon]:
    """Partition a tile into 3 sections from anchor through 3 perimeter points."""
    gs = corners[1][0] - corners[0][0]  # grid_size
    sections = []
    for i in range(3):
        p1 = pts[i]
        p2 = pts[(i + 1) % 3]
        verts = [anchor, p1]
        idx1 = _get_edge_index(p1, corners, gs)
        idx2 = _get_edge_index(p2, corners, gs)
        j = idx1
        while j != idx2:
            verts.append(corners[(j + 1) % 4])
            j = (j + 1) % 4
        verts.append(p2)
        try:
            poly = Polygon(verts)
            if poly.is_valid and poly.area > 0:
                sections.append(poly)
        except Exception:
            pass
    return sections

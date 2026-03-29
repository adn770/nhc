"""SVG floor renderer — Dyson Logos style.

Generates a static SVG image of a dungeon floor from nhc's Level model.
Black and white only. The SVG contains rooms, corridors, walls, doors
(as gaps in walls), stairs (triangular parallel lines), and procedural
cross-hatching from dmap. No entities — those are overlaid by the
browser client using the tileset.

Hatching algorithm ported from ppdf/dmap_lib/rendering/hatching.py.
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import noise as _noise
from shapely.geometry import LineString, Point, Polygon

if TYPE_CHECKING:
    from nhc.dungeon.model import Level

# ── Constants ────────────────────────────────────────────────────

CELL = 32          # pixels per grid cell
PADDING = 32       # padding around the map (room for hatching)
WALL_WIDTH = 4.0   # wall stroke width (bold Dyson style)
WALL_THIN = 2.0    # thinner wall for corridors
GRID_WIDTH = 0.3   # soft floor grid line width
DOOR_GAP = 0.7     # fraction of cell for door opening
HATCH_UNDERLAY = "#D0D0D0"

# ── Colors (black & white) ──────────────────────────────────────

BG = "#FFFFFF"
INK = "#000000"
GRID_COLOR = "#CCCCCC"


def render_floor_svg(level: "Level", seed: int = 0) -> str:
    """Generate a Dyson-style SVG for a dungeon floor."""
    w = level.width * CELL + 2 * PADDING
    h = level.height * CELL + 2 * PADDING

    svg: list[str] = []
    svg.append(
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')
    svg.append(f'<g transform="translate({PADDING},{PADDING})">')

    # Layer 1: Room shadows (subtle)
    _render_room_shadows(svg, level)

    # Layer 2: Floor fills
    _render_floors(svg, level)

    # Layer 3: Soft floor grid
    _render_floor_grid(svg, level)

    # Layer 4: Walls (with door gaps)
    door_set = _collect_doors(level)
    _render_walls(svg, level, door_set)

    # Layer 5: Door notches (small marks at wall openings)
    _render_doors(svg, level)

    # Layer 6: Stairs (triangular parallel lines)
    _render_stairs(svg, level)

    # Layer 7: dmap-style hatching
    _render_hatching_dmap(svg, level, seed)

    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


# ── Helpers ──────────────────────────────────────────────────────

def _is_floor(level: "Level", x: int, y: int) -> bool:
    from nhc.dungeon.model import Terrain
    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER)


def _is_door(level: "Level", x: int, y: int) -> bool:
    if not level.in_bounds(x, y):
        return False
    f = level.tiles[y][x].feature
    return f in ("door_closed", "door_open", "door_secret", "door_locked")


def _collect_doors(level: "Level") -> set[tuple[int, int]]:
    doors = set()
    for y in range(level.height):
        for x in range(level.width):
            if _is_door(level, x, y):
                doors.add((x, y))
    return doors


# ── Layer renderers ──────────────────────────────────────────────

def _render_room_shadows(svg: list[str], level: "Level") -> None:
    """Subtle offset shadow for rooms."""
    for room in level.rooms:
        r = room.rect
        svg.append(
            f'<rect x="{r.x * CELL + 3}" y="{r.y * CELL + 3}" '
            f'width="{r.width * CELL}" height="{r.height * CELL}" '
            f'fill="{INK}" opacity="0.08"/>'
        )


def _render_floors(svg: list[str], level: "Level") -> None:
    """Fill floor tiles with white."""
    for y in range(level.height):
        for x in range(level.width):
            if _is_floor(level, x, y) or _is_door(level, x, y):
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" fill="{BG}"/>'
                )


def _render_floor_grid(svg: list[str], level: "Level") -> None:
    """Draw a soft thin grid on room floors (not corridors)."""
    segments: list[str] = []
    for y in range(level.height):
        for x in range(level.width):
            if not _is_floor(level, x, y):
                continue
            tile = level.tiles[y][x]
            if tile.is_corridor:
                continue
            px, py = x * CELL, y * CELL
            # Right edge (avoid double-draw)
            if _is_floor(level, x + 1, y):
                nr = level.tiles[y][x + 1]
                if not nr.is_corridor:
                    segments.append(
                        f'M{px + CELL},{py} L{px + CELL},{py + CELL}')
            # Bottom edge
            if _is_floor(level, x, y + 1):
                nb = level.tiles[y + 1][x]
                if not nb.is_corridor:
                    segments.append(
                        f'M{px},{py + CELL} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{GRID_COLOR}" stroke-width="{GRID_WIDTH}"/>'
        )


def _render_walls(
    svg: list[str], level: "Level",
    door_set: set[tuple[int, int]],
) -> None:
    """Render wall edges, skipping edges adjacent to door tiles."""
    segments: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not (_is_floor(level, x, y) or (x, y) in door_set):
                continue
            px, py = x * CELL, y * CELL

            # For door tiles, don't draw wall edges on the sides
            # that connect to floor (that's the opening)
            is_this_door = (x, y) in door_set

            # Top edge
            if not _is_floor(level, x, y - 1) and (x, y - 1) not in door_set:
                if not is_this_door or not _door_opens_vertically(level, x, y):
                    segments.append(f'M{px},{py} L{px + CELL},{py}')
            # Bottom edge
            if not _is_floor(level, x, y + 1) and (x, y + 1) not in door_set:
                if not is_this_door or not _door_opens_vertically(level, x, y):
                    segments.append(
                        f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            # Left edge
            if not _is_floor(level, x - 1, y) and (x - 1, y) not in door_set:
                if not is_this_door or _door_opens_vertically(level, x, y):
                    segments.append(f'M{px},{py} L{px},{py + CELL}')
            # Right edge
            if not _is_floor(level, x + 1, y) and (x + 1, y) not in door_set:
                if not is_this_door or _door_opens_vertically(level, x, y):
                    segments.append(
                        f'M{px + CELL},{py} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )


def _door_opens_vertically(level: "Level", x: int, y: int) -> bool:
    """True if the door connects left-right (passage is vertical)."""
    return _is_floor(level, x - 1, y) or _is_floor(level, x + 1, y)


def _render_doors(svg: list[str], level: "Level") -> None:
    """Draw small notch marks at door positions in the wall gap."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not tile.feature:
                continue
            if tile.feature not in ("door_closed", "door_open",
                                    "door_secret", "door_locked"):
                continue

            px, py = x * CELL, y * CELL
            vertical = _door_opens_vertically(level, x, y)
            notch_len = CELL * 0.25

            if tile.feature == "door_open":
                continue  # Open doors are just gaps, no mark

            # Draw short perpendicular notch lines at both ends
            if vertical:
                # Door passage is vertical — notches on left and right walls
                svg.append(
                    f'<line x1="{px}" y1="{py + CELL / 2 - notch_len}" '
                    f'x2="{px}" y2="{py + CELL / 2 + notch_len}" '
                    f'stroke="{INK}" stroke-width="{WALL_WIDTH + 1}"/>')
                svg.append(
                    f'<line x1="{px + CELL}" '
                    f'y1="{py + CELL / 2 - notch_len}" '
                    f'x2="{px + CELL}" '
                    f'y2="{py + CELL / 2 + notch_len}" '
                    f'stroke="{INK}" stroke-width="{WALL_WIDTH + 1}"/>')
            else:
                # Door passage is horizontal — notches on top and bottom
                svg.append(
                    f'<line x1="{px + CELL / 2 - notch_len}" y1="{py}" '
                    f'x2="{px + CELL / 2 + notch_len}" y2="{py}" '
                    f'stroke="{INK}" stroke-width="{WALL_WIDTH + 1}"/>')
                svg.append(
                    f'<line x1="{px + CELL / 2 - notch_len}" '
                    f'y1="{py + CELL}" '
                    f'x2="{px + CELL / 2 + notch_len}" '
                    f'y2="{py + CELL}" '
                    f'stroke="{INK}" stroke-width="{WALL_WIDTH + 1}"/>')


def _render_stairs(svg: list[str], level: "Level") -> None:
    """Render stairs as triangular shapes with parallel vertical lines.

    stairs_down (>) : triangle pointing right, vertical lines inside
    stairs_up   (<) : triangle pointing left, vertical lines inside
    Mimics the terminal < and > characters.
    """
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in ("stairs_down", "stairs_up"):
                continue

            px, py = x * CELL, y * CELL
            margin = CELL * 0.15
            down = tile.feature == "stairs_down"

            if down:
                # Triangle pointing right: >
                # Tip on the right, base on the left
                tip_x = px + CELL - margin
                base_x = px + margin
                top_y = py + margin
                bot_y = py + CELL - margin
                mid_y = py + CELL / 2
                svg.append(
                    f'<polygon points='
                    f'"{base_x:.1f},{top_y:.1f} '
                    f'{tip_x:.1f},{mid_y:.1f} '
                    f'{base_x:.1f},{bot_y:.1f}" '
                    f'fill="none" stroke="{INK}" '
                    f'stroke-width="1.5" stroke-linejoin="round"/>')
                # Parallel vertical lines inside the triangle
                tri_width = tip_x - base_x
                n_lines = 4
                for i in range(1, n_lines + 1):
                    lx = base_x + tri_width * i / (n_lines + 1)
                    # Find triangle height at this x
                    frac = (lx - base_x) / tri_width
                    half_h = (bot_y - top_y) / 2 * (1 - frac)
                    svg.append(
                        f'<line x1="{lx:.1f}" '
                        f'y1="{mid_y - half_h:.1f}" '
                        f'x2="{lx:.1f}" '
                        f'y2="{mid_y + half_h:.1f}" '
                        f'stroke="{INK}" stroke-width="1"/>')
            else:
                # Triangle pointing left: <
                tip_x = px + margin
                base_x = px + CELL - margin
                top_y = py + margin
                bot_y = py + CELL - margin
                mid_y = py + CELL / 2
                svg.append(
                    f'<polygon points='
                    f'"{base_x:.1f},{top_y:.1f} '
                    f'{tip_x:.1f},{mid_y:.1f} '
                    f'{base_x:.1f},{bot_y:.1f}" '
                    f'fill="none" stroke="{INK}" '
                    f'stroke-width="1.5" stroke-linejoin="round"/>')
                tri_width = base_x - tip_x
                n_lines = 4
                for i in range(1, n_lines + 1):
                    lx = base_x - tri_width * i / (n_lines + 1)
                    frac = (base_x - lx) / tri_width
                    half_h = (bot_y - top_y) / 2 * (1 - frac)
                    svg.append(
                        f'<line x1="{lx:.1f}" '
                        f'y1="{mid_y - half_h:.1f}" '
                        f'x2="{lx:.1f}" '
                        f'y2="{mid_y + half_h:.1f}" '
                        f'stroke="{INK}" stroke-width="1"/>')


# ── dmap-style hatching ──────────────────────────────────────────

def _render_hatching_dmap(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Procedural cross-hatching ported from dmap's HatchingRenderer.

    Uses Shapely for geometry clipping, Perlin noise for organic
    displacement, and tile-based section partitioning.
    """
    random.seed(seed)
    dungeon_poly = _build_dungeon_polygon(level)
    if dungeon_poly.is_empty:
        return

    hatch_distance_limit = 2.0 * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    tile_fills: list[str] = []
    hatch_lines: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if dungeon_poly.contains(center):
                continue
            dist = dungeon_poly.boundary.distance(center)
            if dist > hatch_distance_limit:
                continue

            # Grey underlay tile
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            # Perlin-displaced cluster anchor
            nr = CELL * 0.1
            dx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            dy = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = ((gx + 0.5) * CELL + dx, (gy + 0.5) * CELL + dy)

            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]

            # Pick 3 random perimeter points to partition tile
            pts = _pick_section_points(corners, anchor, CELL)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    angle = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    angle = random.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1])
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    cx = section.centroid.x
                    cy = section.centroid.y
                    perp_x = math.cos(angle + math.pi / 2) * offset
                    perp_y = math.sin(angle + math.pi / 2) * offset
                    line = LineString([
                        (cx + perp_x - math.cos(angle) * diag,
                         cy + perp_y - math.sin(angle) * diag),
                        (cx + perp_x + math.cos(angle) * diag,
                         cy + perp_y + math.sin(angle) * diag),
                    ])
                    clipped = section.intersection(line)
                    if clipped.is_empty or not isinstance(clipped, LineString):
                        continue
                    p1, p2 = list(clipped.coords)
                    # Perlin wobble
                    wb = CELL * 0.03
                    p1 = (
                        p1[0] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=10) * wb,
                        p1[1] + _noise.pnoise2(
                            p1[0] * 0.1, p1[1] * 0.1, base=11) * wb,
                    )
                    p2 = (
                        p2[0] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=12) * wb,
                        p2[1] + _noise.pnoise2(
                            p2[0] * 0.1, p2[1] * 0.1, base=13) * wb,
                    )
                    sw = random.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" stroke-width="{sw:.2f}" '
                        f'stroke-linecap="round"/>')

    # Render underlay first, then hatch lines on top
    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')


def _build_dungeon_polygon(level: "Level") -> Polygon:
    """Build a Shapely polygon covering all floor/door tiles."""
    from shapely.ops import unary_union
    polys = []
    for y in range(level.height):
        for x in range(level.width):
            if _is_floor(level, x, y) or _is_door(level, x, y):
                polys.append(Polygon([
                    (x * CELL, y * CELL),
                    ((x + 1) * CELL, y * CELL),
                    ((x + 1) * CELL, (y + 1) * CELL),
                    (x * CELL, (y + 1) * CELL),
                ]))
    if not polys:
        return Polygon()
    return unary_union(polys)


def _pick_section_points(
    corners: list[tuple[float, float]],
    anchor: tuple[float, float],
    grid_size: float,
) -> list[tuple[float, float]]:
    """Pick 3 random perimeter points and sort by angle from anchor."""

    def _random_perimeter_point(edge: int) -> tuple[float, float]:
        t = random.uniform(0, grid_size)
        if edge == 0:
            return (corners[0][0] + t, corners[0][1])
        if edge == 1:
            return (corners[1][0], corners[1][1] + t)
        if edge == 2:
            return (corners[2][0] - t, corners[2][1])
        return (corners[3][0], corners[3][1] - t)

    edges = [random.randint(0, 3) for _ in range(3)]
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

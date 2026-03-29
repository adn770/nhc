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

    # Layer 3: Soft floor grid (rooms + corridors)
    _render_floor_grid(svg, level)

    # Layer 3b: Floor detail — cracks and stones
    _render_floor_detail(svg, level, seed)

    # Layer 4: Walls (solid, no gaps)
    _render_walls(svg, level)

    # Layer 5: Doors (punch white gap in wall, draw notch marks)
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
    """Draw a hand-drawn style grid on all floor tiles.

    Uses Perlin noise to slightly wobble line endpoints and vary
    stroke width, giving an organic hand-drawn look.
    """
    rng = random.Random(41)
    segments: list[str] = []
    wobble = CELL * 0.05  # snake amplitude
    n_sub = 5  # subdivisions per grid line for the snake effect

    for y in range(level.height):
        for x in range(level.width):
            if not (_is_floor(level, x, y) or _is_door(level, x, y)):
                continue
            px, py = x * CELL, y * CELL

            # Right edge (vertical line)
            if _is_floor(level, x + 1, y) or _is_door(level, x + 1, y):
                bx = px + CELL
                pts = []
                for i in range(n_sub + 1):
                    t = i / n_sub
                    ly = py + t * CELL
                    lx = bx + _noise.pnoise2(
                        x * 0.7 + t * 0.5, y * 0.7, base=20) * wobble
                    pts.append((lx, ly))
                # Small gap near the middle for discontinuity
                gap_pos = rng.randint(1, n_sub - 1)
                seg = f'M{pts[0][0]:.1f},{pts[0][1]:.1f}'
                for i in range(1, len(pts)):
                    if i == gap_pos and rng.random() < 0.25:
                        seg += f' M{pts[i][0]:.1f},{pts[i][1]:.1f}'
                    else:
                        seg += f' L{pts[i][0]:.1f},{pts[i][1]:.1f}'
                segments.append(seg)

            # Bottom edge (horizontal line)
            if _is_floor(level, x, y + 1) or _is_door(level, x, y + 1):
                by = py + CELL
                pts = []
                for i in range(n_sub + 1):
                    t = i / n_sub
                    lx = px + t * CELL
                    ly = by + _noise.pnoise2(
                        x * 0.3 + t * 0.5, y * 0.7, base=24) * wobble
                    pts.append((lx, ly))
                gap_pos = rng.randint(1, n_sub - 1)
                seg = f'M{pts[0][0]:.1f},{pts[0][1]:.1f}'
                for i in range(1, len(pts)):
                    if i == gap_pos and rng.random() < 0.25:
                        seg += f' M{pts[i][0]:.1f},{pts[i][1]:.1f}'
                    else:
                        seg += f' L{pts[i][0]:.1f},{pts[i][1]:.1f}'
                segments.append(seg)

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
            f'opacity="0.7" stroke-linecap="round"/>'
        )


def _render_floor_detail(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Scatter cracks and small stones on floor tiles.

    Cracks are thin jagged lines. Stones are small rounded empty
    ellipses. Both use low opacity for a subtle worn-stone effect.
    """
    rng = random.Random(seed + 99)
    cracks: list[str] = []
    stones: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not _is_floor(level, x, y):
                continue
            px, py = x * CELL, y * CELL

            # ~8% chance of a crack triangle at a tile corner
            if rng.random() < 0.08:
                # Pick a random corner and draw a small triangle
                # connecting two orthogonal grid lines
                corner = rng.randint(0, 3)
                # Triangle size along each grid line
                s1 = rng.uniform(CELL * 0.15, CELL * 0.4)
                s2 = rng.uniform(CELL * 0.15, CELL * 0.4)
                if corner == 0:    # top-left
                    tri = (f'{px},{py} '
                           f'{px + s1},{py} '
                           f'{px},{py + s2}')
                elif corner == 1:  # top-right
                    tri = (f'{px + CELL},{py} '
                           f'{px + CELL - s1},{py} '
                           f'{px + CELL},{py + s2}')
                elif corner == 2:  # bottom-left
                    tri = (f'{px},{py + CELL} '
                           f'{px + s1},{py + CELL} '
                           f'{px},{py + CELL - s2}')
                else:              # bottom-right
                    tri = (f'{px + CELL},{py + CELL} '
                           f'{px + CELL - s1},{py + CELL} '
                           f'{px + CELL},{py + CELL - s2}')
                cracks.append(tri)

            # ~6% chance of a stone
            if rng.random() < 0.06:
                sx = px + rng.uniform(CELL * 0.25, CELL * 0.75)
                sy = py + rng.uniform(CELL * 0.25, CELL * 0.75)
                rx = rng.uniform(2, CELL * 0.15)
                ry = rng.uniform(2, CELL * 0.12)
                angle = rng.uniform(0, 180)
                stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
                    f'fill="none" stroke="{INK}" stroke-width="0.4"/>')

    if cracks:
        polys = "".join(
            f'<polygon points="{tri}" fill="none" '
            f'stroke="{INK}" stroke-width="0.5" '
            f'stroke-linejoin="round"/>'
            for tri in cracks
        )
        svg.append(f'<g opacity="0.5">{polys}</g>')
    if stones:
        svg.append(f'<g opacity="0.8">{"".join(stones)}</g>')


def _render_walls(svg: list[str], level: "Level") -> None:
    """Render wall edges between walkable and non-walkable tiles.

    Draws walls everywhere including through door tiles. Door openings
    are punched afterwards by _render_doors.
    """
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            px, py = x * CELL, y * CELL
            if not _walkable(x, y - 1):
                segments.append(f'M{px},{py} L{px + CELL},{py}')
            if not _walkable(x, y + 1):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            if not _walkable(x - 1, y):
                segments.append(f'M{px},{py} L{px},{py + CELL}')
            if not _walkable(x + 1, y):
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
    """Draw doors as thin rectangles spanning the wall.

    The door tile replaces a wall tile — floor is on both sides.
    The rectangle straddles the wall edge: ~80% cell width across
    the wall direction (leaving small wall stubs at corners), ~30%
    cell depth along the passage direction. White fill erases the
    wall, thin stroke draws the door frame.
    """
    door_stroke = WALL_WIDTH * 0.5  # thinner than walls
    wall_span = 0.80   # fraction of cell across the wall
    pass_depth = 0.30   # fraction of cell along the passage

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

            if vertical:
                # Passage is left-right, wall runs top-bottom.
                # Rectangle is tall (spans wall) and narrow (passage).
                dw = CELL * pass_depth
                dh = CELL * wall_span
            else:
                # Passage is top-bottom, wall runs left-right.
                # Rectangle is wide (spans wall) and short (passage).
                dw = CELL * wall_span
                dh = CELL * pass_depth

            # Center the rectangle on the door tile
            dx = px + (CELL - dw) / 2
            dy = py + (CELL - dh) / 2

            # White fill to erase the wall underneath
            # Slightly oversized to cover wall stroke
            pad = WALL_WIDTH
            svg.append(
                f'<rect x="{dx - pad:.1f}" y="{dy - pad:.1f}" '
                f'width="{dw + pad * 2:.1f}" '
                f'height="{dh + pad * 2:.1f}" '
                f'fill="{BG}"/>')

            # Draw the door outline and diagonal corner connections
            if tile.feature != "door_open":
                svg.append(
                    f'<rect x="{dx:.1f}" y="{dy:.1f}" '
                    f'width="{dw:.1f}" height="{dh:.1f}" '
                    f'fill="none" stroke="{INK}" '
                    f'stroke-width="{door_stroke:.1f}"/>')

                # Diagonal lines connecting door corners to wall ends
                if vertical:
                    # Wall runs top-bottom. Door corners connect to
                    # the wall stubs above and below the rectangle.
                    # Top-left corner → wall stub top-left
                    svg.append(
                        f'<line x1="{dx:.1f}" y1="{dy:.1f}" '
                        f'x2="{px:.1f}" y2="{py:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Top-right corner → wall stub top-right
                    svg.append(
                        f'<line x1="{dx + dw:.1f}" y1="{dy:.1f}" '
                        f'x2="{px + CELL:.1f}" y2="{py:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Bottom-left corner → wall stub bottom-left
                    svg.append(
                        f'<line x1="{dx:.1f}" y1="{dy + dh:.1f}" '
                        f'x2="{px:.1f}" y2="{py + CELL:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Bottom-right corner → wall stub bottom-right
                    svg.append(
                        f'<line x1="{dx + dw:.1f}" y1="{dy + dh:.1f}" '
                        f'x2="{px + CELL:.1f}" y2="{py + CELL:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                else:
                    # Wall runs left-right. Door corners connect to
                    # wall stubs left and right of the rectangle.
                    # Top-left → wall stub left-top
                    svg.append(
                        f'<line x1="{dx:.1f}" y1="{dy:.1f}" '
                        f'x2="{px:.1f}" y2="{py:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Top-right → wall stub right-top
                    svg.append(
                        f'<line x1="{dx + dw:.1f}" y1="{dy:.1f}" '
                        f'x2="{px + CELL:.1f}" y2="{py:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Bottom-left → wall stub left-bottom
                    svg.append(
                        f'<line x1="{dx:.1f}" y1="{dy + dh:.1f}" '
                        f'x2="{px:.1f}" y2="{py + CELL:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')
                    # Bottom-right → wall stub right-bottom
                    svg.append(
                        f'<line x1="{dx + dw:.1f}" y1="{dy + dh:.1f}" '
                        f'x2="{px + CELL:.1f}" y2="{py + CELL:.1f}" '
                        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
                        f'stroke-linecap="round"/>')


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

    base_distance_limit = 2.0 * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if dungeon_poly.contains(center):
                continue
            dist = dungeon_poly.boundary.distance(center)

            # Irregular contour: vary distance limit per tile with
            # Perlin noise so the hatching edge flows organically
            noise_var = _noise.pnoise2(
                gx * 0.3, gy * 0.3, base=50) * CELL * 0.8
            tile_limit = base_distance_limit + noise_var
            if dist > tile_limit:
                continue

            # Random discontinuities: skip ~10% of edge tiles
            if dist > base_distance_limit * 0.5 and random.random() < 0.10:
                continue

            # Grey underlay tile
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            # Scatter 0-2 stones of varying sizes in this tile
            n_stones = random.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + random.uniform(0.15, 0.85)) * CELL
                sy = (gy + random.uniform(0.15, 0.85)) * CELL
                rx = random.uniform(2, CELL * 0.25)
                ry = random.uniform(2, CELL * 0.2)
                angle = random.uniform(0, 180)
                sw = random.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#CCCCCC" '
                    f'stroke-width="{sw:.1f}"/>')

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
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')


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

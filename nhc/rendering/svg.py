"""SVG floor renderer — Dyson Logos style.

Generates a static SVG image of a dungeon floor from nhc's Level model.
Black and white only. The SVG contains rooms, corridors, walls, doors
(as gaps in walls), stairs (triangular parallel lines), and procedural
cross-hatching. No entities — those are overlaid by the
browser client using the tileset.

Hatching uses Shapely geometry and Perlin noise for organic effects.
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
HATCH_UNDERLAY = "#D0D0D0"

# ── Colors (black & white) ──────────────────────────────────────

BG = "#F5EDE0"
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

    # Layer 4: Hatching (behind walls)
    _render_hatching(svg, level, seed)

    # Layer 5: Walls (on top of hatching)
    _render_walls(svg, level)

    # Layer 6: Stairs
    _render_stairs(svg, level)

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
    """True for visible doors (not secret — those look like walls)."""
    if not level.in_bounds(x, y):
        return False
    f = level.tiles[y][x].feature
    return f in ("door_closed", "door_open", "door_locked")


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
    """Render walls as a continuous perimeter outline around rooms.

    Lines sit on the boundary between floor and wall tiles, like
    terminal box-drawing characters (┌─┐│└┘). The stroke width
    extends outward into the wall tile, giving the walls visual
    thickness on the non-floor side.
    """
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            px, py = x * CELL, y * CELL
            # Top edge
            if not _walkable(x, y - 1):
                segments.append(f'M{px},{py} L{px + CELL},{py}')
            # Bottom edge
            if not _walkable(x, y + 1):
                segments.append(
                    f'M{px},{py + CELL} L{px + CELL},{py + CELL}')
            # Left edge
            if not _walkable(x - 1, y):
                segments.append(f'M{px},{py} L{px},{py + CELL}')
            # Right edge
            if not _walkable(x + 1, y):
                segments.append(
                    f'M{px + CELL},{py} L{px + CELL},{py + CELL}')

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )


def _render_stairs(svg: list[str], level: "Level") -> None:
    """Render stairs as tapering wedges with parallel step lines.

    Classic dungeon map convention: steps taper in the direction of
    descent. Wide end = current level, narrow end = where stairs go.

    stairs_down (>) : wide on left, narrows to right
    stairs_up   (<) : wide on right, narrows to left
    """
    rail_sw = 1.5
    step_sw = 1.0
    n_steps = 5

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in ("stairs_down", "stairs_up"):
                continue

            px, py = x * CELL, y * CELL
            m = CELL * 0.1  # margin from tile edge
            down = tile.feature == "stairs_down"
            cx = px + CELL / 2
            cy = py + CELL / 2

            # Wide end half-height and narrow end half-height
            wide_h = CELL * 0.4
            narrow_h = CELL * 0.1

            if down:
                # Wide on left, narrow on right
                left_x = px + m
                right_x = px + CELL - m
                # Top rail: top-left → top-right (tapering)
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy - wide_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy - narrow_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Bottom rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy + wide_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy + narrow_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Step lines (vertical, between the rails)
                span = right_x - left_x
                for i in range(n_steps + 1):
                    t = i / n_steps
                    sx = left_x + span * t
                    half = wide_h + (narrow_h - wide_h) * t
                    svg.append(
                        f'<line x1="{sx:.1f}" '
                        f'y1="{cy - half:.1f}" '
                        f'x2="{sx:.1f}" '
                        f'y2="{cy + half:.1f}" '
                        f'stroke="{INK}" stroke-width="{step_sw}" '
                        f'stroke-linecap="round"/>')
            else:
                # Wide on right, narrow on left
                left_x = px + m
                right_x = px + CELL - m
                # Top rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy - narrow_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy - wide_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Bottom rail
                svg.append(
                    f'<line x1="{left_x:.1f}" '
                    f'y1="{cy + narrow_h:.1f}" '
                    f'x2="{right_x:.1f}" '
                    f'y2="{cy + wide_h:.1f}" '
                    f'stroke="{INK}" stroke-width="{rail_sw}" '
                    f'stroke-linecap="round"/>')
                # Step lines
                span = right_x - left_x
                for i in range(n_steps + 1):
                    t = i / n_steps
                    sx = left_x + span * t
                    half = narrow_h + (wide_h - narrow_h) * t
                    svg.append(
                        f'<line x1="{sx:.1f}" '
                        f'y1="{cy - half:.1f}" '
                        f'x2="{sx:.1f}" '
                        f'y2="{cy + half:.1f}" '
                        f'stroke="{INK}" stroke-width="{step_sw}" '
                        f'stroke-linecap="round"/>')


# ── Hatching ─────────────────────────────────────────────────────

def _render_hatching(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Procedural cross-hatching around the dungeon perimeter.

    Uses Shapely for geometry clipping, Perlin noise for organic
    displacement, and tile-based section partitioning.
    """
    random.seed(seed)
    dungeon_poly = _build_dungeon_polygon(level)
    if dungeon_poly.is_empty:
        return

    # Buffer the polygon outward by half the wall width so hatching
    # starts right outside the wall line, not overlapping it
    wall_buffer = WALL_WIDTH
    hatching_boundary = dungeon_poly.buffer(wall_buffer)

    base_distance_limit = 2.0 * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if hatching_boundary.contains(center):
                continue
            dist = hatching_boundary.boundary.distance(center)

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
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
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

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
import re
import noise as _noise
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.polygon import orient as _shapely_orient
from shapely.ops import unary_union

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape, Level,
    OctagonShape, PillShape, Rect, RectShape, Room,
    TempleShape, Terrain,
)
from nhc.dungeon.generators.cellular import CaveShape
from nhc.rendering.terrain_palette import (
    ROOM_TYPE_TINTS, get_palette,
)

# ── Constants ────────────────────────────────────────────────────

CELL = 32          # pixels per grid cell
PILL_ARC_SEGMENTS = 12  # per-cap polygon segments for pill outlines
TEMPLE_ARC_SEGMENTS = 12  # per-cap polygon segments for temple arm caps
PADDING = 32       # padding around the map (must match web client)
WALL_WIDTH = 5.0   # wall stroke width (bold Dyson style)
WALL_THIN = 2.0    # thinner wall for corridors
GRID_WIDTH = 0.3   # soft floor grid line width
HATCH_UNDERLAY = "#D0D0D0"

# ── Colors (black & white) ──────────────────────────────────────

BG = "#F5EDE0"
FLOOR_COLOR = "#FFFFFF"
CAVE_FLOOR_COLOR = "#F5EBD8"  # soft warm brown for cave floors
INK = "#000000"
FLOOR_STONE_FILL = "#E8D5B8"  # soft brown for room floor stones
FLOOR_STONE_STROKE = "#666666"


def render_floor_svg(
    level: "Level", seed: int = 0, hatch_distance: float = 2.0,
) -> str:
    """Generate a Dyson-style SVG for a dungeon floor.

    *hatch_distance* controls how far (in tiles) the cross-hatching
    extends from the dungeon perimeter.  Default 2.0 gives the full
    Dyson look; lower values (e.g. 1.0) reduce SVG complexity and
    rendering time significantly.

    Cave levels always use at least 2 tiles of hatch extent — the
    wider grey halo is a defining feature of the Dyson cavern style
    and matters more than render-time savings at that theme.
    """
    if any(isinstance(r.shape, CaveShape) for r in level.rooms):
        hatch_distance = max(hatch_distance, 2.0)
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

    # Build the unified cave region geometry once: the SVG wall
    # path, the matching jittered wall polygon (clip/fill), and
    # the set of cave-region tiles.  Computed here so the polygon
    # can feed both the dungeon clip (hatching, grid, detail) and
    # the floor/wall renderer.
    cave_rng = random.Random(seed + 0x5A17E5)
    cave_wall_path, cave_wall_poly, cave_tiles = (
        _build_cave_wall_geometry(level, cave_rng)
    )

    # Build dungeon polygon once — used for hatching and grid clips
    dungeon_poly = _build_dungeon_polygon(
        level, cave_wall_poly=cave_wall_poly,
        cave_tiles=cave_tiles,
    )

    # Layer 1: Shadows (rooms + corridors)
    _render_room_shadows(svg, level)
    _render_corridor_shadows(svg, level)

    # Layer 2: Hatching (rooms clipped to exterior of dungeon
    # polygon, corridors hatched one tile on each side)
    _render_hatching(svg, level, seed, dungeon_poly,
                     hatch_distance=hatch_distance,
                     cave_wall_poly=cave_wall_poly)
    _render_corridor_hatching(svg, level, seed)

    # Layer 3: Walls + floor fills
    _render_walls_and_floors(
        svg, level,
        cave_wall_path=cave_wall_path,
        cave_wall_poly=cave_wall_poly,
        cave_tiles=cave_tiles,
    )

    # Layer 3.5: Terrain tints + room-type hints
    _render_terrain_tints(svg, level, dungeon_poly)

    # Layer 4: Floor grid (clipped to interior of dungeon polygon)
    _render_floor_grid(svg, level, dungeon_poly)

    # Layer 5: Floor detail (clipped to interior of dungeon polygon)
    _render_floor_detail(svg, level, seed, dungeon_poly)

    # Layer 6: Terrain detail (wavy lines, grass strokes, etc.)
    _render_terrain_detail(svg, level, seed, dungeon_poly)

    # Layer 7: Stairs
    _render_stairs(svg, level)

    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


HATCH_PATCH_SIZE = 16  # tiles per side of the repeating hatch patch


def render_hatch_svg(seed: int = 0) -> str:
    """Generate a small tileable hatching SVG patch.

    Produces an 8x8 tile patch of Dyson-style cross-hatching that
    the web client stamps across the full hatch canvas using
    createPattern.  Typically under 100 KB.
    """
    size = HATCH_PATCH_SIZE
    w = size * CELL
    h = size * CELL

    svg: list[str] = []
    svg.append(
        f'<svg width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    )
    svg.append(f'<rect width="100%" height="100%" fill="{BG}"/>')

    rng = random.Random(seed + 77)

    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(size):
        for gx in range(size):
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            n_stones = rng.choices(
                [0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},'
                    f'{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                    f'stroke-width="{sw:.1f}"/>')

            nr = CELL * 0.1
            adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
            ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
            anchor = ((gx + 0.5) * CELL + adx,
                      (gy + 0.5) * CELL + ady)

            corners = [
                (gx * CELL, gy * CELL),
                ((gx + 1) * CELL, gy * CELL),
                ((gx + 1) * CELL, (gy + 1) * CELL),
                (gx * CELL, (gy + 1) * CELL),
            ]

            pts = _pick_section_points(corners, anchor, CELL, rng)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    a = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    a = rng.uniform(0, math.pi)

                bounds = section.bounds
                diag = math.hypot(
                    bounds[2] - bounds[0], bounds[3] - bounds[1])
                spacing = CELL * 0.20
                n_lines = max(3, int(diag / spacing))

                for j in range(n_lines):
                    offset = (j - (n_lines - 1) / 2) * spacing
                    scx = section.centroid.x
                    scy = section.centroid.y
                    perp_x = math.cos(a + math.pi / 2) * offset
                    perp_y = math.sin(a + math.pi / 2) * offset
                    line = LineString([
                        (scx + perp_x - math.cos(a) * diag,
                         scy + perp_y - math.sin(a) * diag),
                        (scx + perp_x + math.cos(a) * diag,
                         scy + perp_y + math.sin(a) * diag),
                    ])
                    clipped = section.intersection(line)
                    if (clipped.is_empty
                            or not isinstance(clipped, LineString)):
                        continue
                    p1, p2 = list(clipped.coords)
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
                    lsw = rng.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" '
                        f'y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" '
                        f'y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" '
                        f'stroke-width="{lsw:.2f}" '
                        f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')

    svg.append("</svg>")
    return "\n".join(svg)


# ── Helpers ──────────────────────────────────────────────────────

def _is_floor(level: "Level", x: int, y: int) -> bool:

    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)


def _is_door(level: "Level", x: int, y: int) -> bool:
    """True for visible doors (not secret — those look like walls)."""
    if not level.in_bounds(x, y):
        return False
    f = level.tiles[y][x].feature
    return f in ("door_closed", "door_open", "door_locked")


def _find_doorless_openings(
    room, level: "Level",
) -> list[tuple[int, int, int, int]]:
    """Find edges where corridors enter a room without a door.

    Returns list of (room_x, room_y, corridor_x, corridor_y).
    """

    _DOOR_FEATS = {
        "door_closed", "door_open", "door_secret", "door_locked",
    }
    floor = room.floor_tiles()
    openings = []
    for fx, fy in floor:
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = fx + dx, fy + dy
            if (nx, ny) in floor:
                continue
            nb = level.tile_at(nx, ny)
            if (nb and nb.is_corridor
                    and nb.terrain == Terrain.FLOOR
                    and nb.feature not in _DOOR_FEATS):
                openings.append((fx, fy, nx, ny))
    return openings


def _outline_with_gaps(
    room, outline_el: str,
    openings: list[tuple[int, int, int, int]],
) -> tuple[str, list[str]]:
    """Modify a smooth outline to have gaps at corridor openings.

    Returns (gapped_svg_element, wall_extension_segments).

    For each opening, finds where the corridor walls intersect the
    room's geometric outline, gaps the outline there, and adds
    line segments extending the corridor walls to the intersection
    points.
    """

    shape = room.shape
    r = room.rect

    # Compute gap cut points on the outline for each opening.
    gaps = []  # list of (point_a, point_b) on the outline
    extensions = []  # SVG path segments for corridor wall extensions

    for fx, fy, cx, cy in openings:
        dx, dy = cx - fx, cy - fy
        if dy != 0:  # N/S corridor → vertical walls
            wall_a = (fx * CELL, fy * CELL if dy == -1
                      else (fy + 1) * CELL)
            wall_b = ((fx + 1) * CELL, wall_a[1])
        else:  # E/W corridor → horizontal walls
            wall_a = (fx * CELL if dx == -1
                      else (fx + 1) * CELL, fy * CELL)
            wall_b = (wall_a[0], (fy + 1) * CELL)

        hit_a = _intersect_outline(shape, r, wall_a, dx, dy)
        hit_b = _intersect_outline(shape, r, wall_b, dx, dy)
        if hit_a and hit_b:
            gaps.append((hit_a, hit_b))
            # Extend corridor walls from arc intersection to
            # the far end of the corridor tile (away from room)
            if dy != 0:
                far_y = cy * CELL if dy == -1 else (cy + 1) * CELL
                extensions.append(
                    f'M{hit_a[0]:.1f},{hit_a[1]:.1f} '
                    f'L{wall_a[0]:.1f},{far_y:.1f}'
                )
                extensions.append(
                    f'M{hit_b[0]:.1f},{hit_b[1]:.1f} '
                    f'L{wall_b[0]:.1f},{far_y:.1f}'
                )
            else:
                far_x = cx * CELL if dx == -1 else (cx + 1) * CELL
                extensions.append(
                    f'M{hit_a[0]:.1f},{hit_a[1]:.1f} '
                    f'L{far_x:.1f},{wall_a[1]:.1f}'
                )
                extensions.append(
                    f'M{hit_b[0]:.1f},{hit_b[1]:.1f} '
                    f'L{far_x:.1f},{wall_b[1]:.1f}'
                )

    if not gaps:
        return outline_el, extensions

    # Build gapped outline based on shape type
    if isinstance(shape, CircleShape):
        gapped = _circle_with_gaps(shape, r, gaps)
    elif isinstance(
        shape,
        (OctagonShape, CrossShape, PillShape, TempleShape, HybridShape),
    ):
        gapped = _polygon_with_gaps(shape, r, gaps)
    else:
        return outline_el, extensions

    return gapped if gapped else outline_el, extensions


def _intersect_outline(
    shape, rect, wall_point: tuple[float, float],
    dx: int, dy: int,
) -> tuple[float, float] | None:
    """Find where a corridor wall line hits the room outline.

    *wall_point* is one end of a corridor wall on the tile edge.
    *(dx, dy)* is the direction from room to corridor.
    The wall extends inward (opposite to dx, dy) until it hits
    the outline.
    """

    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL
    wx, wy = wall_point

    if isinstance(shape, CircleShape):
        d = shape._diameter(r)
        radius = d * CELL / 2
        ccx = px + pw / 2
        ccy = py + ph / 2
        return _intersect_circle(ccx, ccy, radius, wx, wy, dx, dy)

    if isinstance(shape, HybridShape):
        return _intersect_hybrid(shape, r, wx, wy, dx, dy)

    if isinstance(
        shape, (OctagonShape, CrossShape, PillShape, TempleShape),
    ):
        verts = _polygon_vertices(shape, r)
        return _intersect_polygon_edges(verts, wx, wy, dx, dy)

    return None


def _intersect_circle(
    ccx: float, ccy: float, radius: float,
    wx: float, wy: float, dx: int, dy: int,
) -> tuple[float, float] | None:
    """Intersect a corridor wall line with the circle.

    For N/S corridors (dx=0): walls are vertical at x=wx,
    intersect x=wx with circle.
    For E/W corridors (dy=0): walls are horizontal at y=wy,
    intersect y=wy with circle.
    """
    if dy != 0:
        # N/S corridor → vertical wall at x=wx
        rel = wx - ccx
        if abs(rel) >= radius:
            return None
        offset = math.sqrt(radius * radius - rel * rel)
        if dy < 0:
            return (wx, ccy - offset)
        else:
            return (wx, ccy + offset)
    else:
        # E/W corridor → horizontal wall at y=wy
        rel = wy - ccy
        if abs(rel) >= radius:
            return None
        offset = math.sqrt(radius * radius - rel * rel)
        if dx < 0:
            return (ccx - offset, wy)
        else:
            return (ccx + offset, wy)


def _intersect_line_seg(
    p1: tuple[float, float], p2: tuple[float, float],
    wx: float, wy: float, dx: int, dy: int,
) -> tuple[float, float] | None:
    """Intersect a corridor wall line with a line segment p1→p2.

    The corridor wall is a vertical line (x=wx) for N/S corridors
    or horizontal line (y=wy) for E/W corridors.
    """
    ax, ay = p1
    bx, by = p2
    if dy != 0:
        # Vertical line x=wx
        if abs(bx - ax) < 1e-9:
            return None  # parallel
        t = (wx - ax) / (bx - ax)
        if t < 0 or t > 1:
            return None
        iy = ay + t * (by - ay)
        return (wx, iy)
    else:
        # Horizontal line y=wy
        if abs(by - ay) < 1e-9:
            return None
        t = (wy - ay) / (by - ay)
        if t < 0 or t > 1:
            return None
        ix = ax + t * (bx - ax)
        return (ix, wy)


def _intersect_hybrid(
    shape, rect, wx: float, wy: float,
    dx: int, dy: int,
) -> tuple[float, float] | None:
    """Intersect a corridor wall with a hybrid room outline."""

    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if shape.split == "horizontal":
        mid = py + (r.height // 2) * CELL
        # Determine which sub-shape the wall hits based on wy
        if wy <= mid:
            sub = shape.left
            sub_py, sub_ph = py, mid - py
        else:
            sub = shape.right
            sub_py, sub_ph = mid, py + ph - mid
    else:
        mid = px + (r.width // 2) * CELL
        if wx <= mid:
            sub = shape.left
            sub_px, sub_pw = px, mid - px
        else:
            sub = shape.right
            sub_px, sub_pw = mid, px + pw - mid

    if isinstance(sub, CircleShape):
        if shape.split == "horizontal":

            tw = r.width
            th = int(sub_ph / CELL)
            d = sub._diameter(Rect(0, 0, tw, th))
            radius = d * CELL / 2
            ccx = px + pw / 2
            ccy = sub_py + sub_ph / 2
        else:

            tw = int(sub_pw / CELL)
            th = r.height
            d = sub._diameter(Rect(0, 0, tw, th))
            radius = d * CELL / 2
            ccx = sub_px + sub_pw / 2
            ccy = py + ph / 2

        arc_hit = _intersect_circle(ccx, ccy, radius, wx, wy, dx, dy)

        # Also check the diagonal transition lines that connect
        # the arc endpoints to the rect half.  The corridor wall
        # might intersect the diagonal instead of the arc.
        if shape.split == "horizontal":
            mid_val = mid
            if sub == shape.left:  # circle on top
                arc_ep = (ccx + radius, ccy)  # right end
                diag_end = (px + pw, mid_val)
                arc_ep2 = (ccx - radius, ccy)  # left end
                diag_end2 = (px, mid_val)
            else:  # circle on bottom
                arc_ep = (ccx - radius, ccy)
                diag_end = (px, mid_val)
                arc_ep2 = (ccx + radius, ccy)
                diag_end2 = (px + pw, mid_val)
        else:
            mid_val = mid
            if sub == shape.left:  # circle on left
                arc_ep = (ccx, ccy + radius)  # bottom end
                diag_end = (mid_val, py + ph)
                arc_ep2 = (ccx, ccy - radius)  # top end
                diag_end2 = (mid_val, py)
            else:  # circle on right
                arc_ep = (ccx, ccy - radius)
                diag_end = (mid_val, py)
                arc_ep2 = (ccx, ccy + radius)
                diag_end2 = (mid_val, py + ph)

        # Check both diagonals
        diag_hit = _intersect_line_seg(
            arc_ep, diag_end, wx, wy, dx, dy)
        diag_hit2 = _intersect_line_seg(
            arc_ep2, diag_end2, wx, wy, dx, dy)

        # Return the hit closest to the corridor (furthest in
        # the corridor direction from the room center)
        candidates = [h for h in [arc_hit, diag_hit, diag_hit2]
                       if h is not None]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Pick the one furthest in the corridor direction
        def _dist_toward_corridor(pt):
            return pt[0] * dx + pt[1] * dy
        return max(candidates, key=_dist_toward_corridor)

    if isinstance(sub, (OctagonShape,)):
        # Build sub-shape polygon and intersect

        if shape.split == "horizontal":
            sub_rect = Rect(r.x, int(sub_py / CELL), r.width,
                            int(sub_ph / CELL))
        else:
            sub_rect = Rect(int(sub_px / CELL), r.y,
                            int(sub_pw / CELL), r.height)
        verts = _polygon_vertices(sub, sub_rect)
        return _intersect_polygon_edges(verts, wx, wy, dx, dy)

    # RectShape — wall is on the bounding rect edge, intersection
    # is just the wall point itself (no extension needed)
    return (wx, wy)


def _polygon_vertices(shape, rect) -> list[tuple[float, float]]:
    """Get pixel-space vertices for an octagon, cross, pill,
    temple, or hybrid shape."""

    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if isinstance(shape, PillShape):
        return _pill_vertices(shape, rect)

    if isinstance(shape, TempleShape):
        return _temple_vertices(shape, rect)

    if isinstance(shape, HybridShape):
        return _hybrid_vertices(shape, rect)

    if isinstance(shape, OctagonShape):
        clip = max(1, min(r.width, r.height) // 3) * CELL
        return [
            (px + clip, py),
            (px + pw - clip, py),
            (px + pw, py + clip),
            (px + pw, py + ph - clip),
            (px + pw - clip, py + ph),
            (px + clip, py + ph),
            (px, py + ph - clip),
            (px, py + clip),
        ]
    if isinstance(shape, CrossShape):
        # Match the tile-based floor_tiles integer math exactly
        cx_tile = r.x + r.width // 2
        cy_tile = r.y + r.height // 2
        bar_w = max(2, r.width // 3)
        bar_h = max(2, r.height // 3)
        h_left = cx_tile - bar_w // 2
        h_right = h_left + bar_w
        v_top = cy_tile - bar_h // 2
        v_bottom = v_top + bar_h
        # Convert to pixel coords
        vl = h_left * CELL
        vr = h_right * CELL
        ht = v_top * CELL
        hb = v_bottom * CELL
        return [
            (vl, py),           # top-left of vertical bar
            (vr, py),           # top-right of vertical bar
            (vr, ht),           # inner corner: right arm top
            (px + pw, ht),      # right arm top-right
            (px + pw, hb),      # right arm bottom-right
            (vr, hb),           # inner corner: right arm bottom
            (vr, py + ph),      # bottom-right of vertical bar
            (vl, py + ph),      # bottom-left of vertical bar
            (vl, hb),           # inner corner: left arm bottom
            (px, hb),           # left arm bottom-left
            (px, ht),           # left arm top-left
            (vl, ht),           # inner corner: left arm top
        ]
    return []


def _pill_vertices(
    shape: "PillShape", rect,
) -> list[tuple[float, float]]:
    """Approximate a pill outline as a closed polygon.

    Uses two flat long sides plus two 180° arcs discretised into
    *PILL_ARC_SEGMENTS* segments each.  The resulting polygon is
    compatible with ``_intersect_polygon_edges`` and
    ``_polygon_with_gaps``.
    """
    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL
    d = shape._diameter(r)
    r_pix = d * CELL / 2.0

    horizontal = r.width >= r.height
    # The pill is the cap-diameter in the short dimension, centered
    # in that axis.  Compute its pixel bounding box.
    if horizontal:
        bx = px
        by = py + (ph - d * CELL) / 2.0
        bw = pw
        bh = d * CELL
    else:
        bx = px + (pw - d * CELL) / 2.0
        by = py
        bw = d * CELL
        bh = ph

    segs = PILL_ARC_SEGMENTS
    verts: list[tuple[float, float]] = []

    if horizontal:
        cy = by + r_pix
        left_cx = bx + r_pix
        right_cx = bx + bw - r_pix
        # Top straight edge: left_cx → right_cx at y = by
        verts.append((left_cx, by))
        verts.append((right_cx, by))
        # Right semicircle from top (-pi/2) clockwise to bottom (+pi/2)
        for i in range(1, segs):
            ang = -math.pi / 2 + math.pi * i / segs
            verts.append(
                (right_cx + r_pix * math.cos(ang),
                 cy + r_pix * math.sin(ang))
            )
        # Bottom straight edge: right_cx → left_cx at y = by + bh
        verts.append((right_cx, by + bh))
        verts.append((left_cx, by + bh))
        # Left semicircle from bottom (pi/2) clockwise to top (3*pi/2)
        for i in range(1, segs):
            ang = math.pi / 2 + math.pi * i / segs
            verts.append(
                (left_cx + r_pix * math.cos(ang),
                 cy + r_pix * math.sin(ang))
            )
    else:
        cx = bx + r_pix
        top_cy = by + r_pix
        bot_cy = by + bh - r_pix
        # Right straight edge: top_cy → bot_cy at x = bx + bw
        verts.append((bx + bw, top_cy))
        verts.append((bx + bw, bot_cy))
        # Bottom semicircle from right (0) clockwise to left (pi)
        for i in range(1, segs):
            ang = math.pi * i / segs
            verts.append(
                (cx + r_pix * math.cos(ang),
                 bot_cy + r_pix * math.sin(ang))
            )
        # Left straight edge: bot_cy → top_cy at x = bx
        verts.append((bx, bot_cy))
        verts.append((bx, top_cy))
        # Top semicircle from left (pi) clockwise to right (2*pi)
        for i in range(1, segs):
            ang = math.pi + math.pi * i / segs
            verts.append(
                (cx + r_pix * math.cos(ang),
                 top_cy + r_pix * math.sin(ang))
            )

    return verts


def _temple_vertices(
    shape: "TempleShape", rect,
) -> list[tuple[float, float]]:
    """Approximate a temple outline as a closed polygon.

    Walks the cross outline clockwise starting at the base of the
    north arm, substituting a semicircular arc for each of the three
    capped arm tips (the fourth arm, ``flat_side``, keeps its
    rectangular tip). Arcs are discretised into
    ``TEMPLE_ARC_SEGMENTS`` segments.
    """
    _, _, h_left, h_right, v_top, v_bottom = shape._bar_widths(rect)
    vl = h_left * CELL
    vr = h_right * CELL
    ht = v_top * CELL
    hb = v_bottom * CELL
    px = rect.x * CELL
    py = rect.y * CELL
    pw = rect.width * CELL
    ph = rect.height * CELL
    bar_w_tiles = h_right - h_left
    bar_h_tiles = v_bottom - v_top
    r_w = bar_w_tiles * CELL / 2.0
    r_h = bar_h_tiles * CELL / 2.0
    mid_x = (vl + vr) / 2.0
    mid_y = (ht + hb) / 2.0

    flat = shape.flat_side
    segs = TEMPLE_ARC_SEGMENTS
    verts: list[tuple[float, float]] = []

    # ── North arm ────────────────────────────────────────────────
    if flat == "north":
        verts.append((vl, py))
        verts.append((vr, py))
    else:
        verts.append((vl, py + r_w))
        center_y = py + r_w
        for i in range(1, segs):
            ang = math.pi - math.pi * i / segs  # pi → 0
            verts.append((
                mid_x + r_w * math.cos(ang),
                center_y - r_w * math.sin(ang),  # sin flipped: tip at top
            ))
        verts.append((vr, py + r_w))
    verts.append((vr, ht))  # NE inner corner

    # ── East arm ─────────────────────────────────────────────────
    if flat == "east":
        verts.append((px + pw, ht))
        verts.append((px + pw, hb))
    else:
        center_x = px + pw - r_h
        verts.append((center_x, ht))
        for i in range(1, segs):
            ang = -math.pi / 2 + math.pi * i / segs  # -pi/2 → pi/2
            verts.append((
                center_x + r_h * math.cos(ang),
                mid_y + r_h * math.sin(ang),
            ))
        verts.append((center_x, hb))
    verts.append((vr, hb))  # SE inner corner

    # ── South arm ────────────────────────────────────────────────
    if flat == "south":
        verts.append((vr, py + ph))
        verts.append((vl, py + ph))
    else:
        center_y = py + ph - r_w
        verts.append((vr, center_y))
        for i in range(1, segs):
            ang = math.pi * i / segs  # 0 → pi
            verts.append((
                mid_x + r_w * math.cos(ang),
                center_y + r_w * math.sin(ang),
            ))
        verts.append((vl, center_y))
    verts.append((vl, hb))  # SW inner corner

    # ── West arm ─────────────────────────────────────────────────
    if flat == "west":
        verts.append((px, hb))
        verts.append((px, ht))
    else:
        center_x = px + r_h
        verts.append((center_x, hb))
        for i in range(1, segs):
            ang = math.pi / 2 + math.pi * i / segs  # pi/2 → 3pi/2
            verts.append((
                center_x + r_h * math.cos(ang),
                mid_y + r_h * math.sin(ang),
            ))
        verts.append((center_x, ht))
    verts.append((vl, ht))  # NW inner corner (close)

    return verts


def _hybrid_vertices(
    shape: "HybridShape", rect,
) -> list[tuple[float, float]]:
    """Approximate a hybrid room outline as a closed polygon.

    Reuses :func:`_hybrid_svg_outline` to build the canonical
    outline (straight segments + one SVG arc) and then expands
    the arc to a polyline via :func:`_svg_path_to_polygon`. The
    resulting polygon is compatible with
    :func:`_intersect_polygon_edges` and
    :func:`_polygon_with_gaps`, so hybrid gap handling goes
    through the same code path as octagons, pills and temples.
    """
    from nhc.dungeon.model import Room

    tmp_room = Room(id="_hybrid_tmp_", rect=rect, shape=shape)
    outline = _hybrid_svg_outline(tmp_room)
    if not outline:
        return []
    poly = _svg_path_to_polygon(outline)
    if poly is None or poly.is_empty:
        return []
    coords = list(poly.exterior.coords)
    # Drop the duplicate closing vertex if present.
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return coords


def _intersect_polygon_edges(
    verts: list[tuple[float, float]],
    wx: float, wy: float, dx: int, dy: int,
) -> tuple[float, float] | None:
    """Find where a corridor wall hits the polygon outline.

    Shoots a ray from (wx, wy) inward (opposite to (dx, dy))
    and returns the nearest polygon edge intersection.
    """
    # Ray direction: inward = opposite of corridor direction
    rdx, rdy = -dx, -dy
    best = None
    best_t = float('inf')

    n = len(verts)
    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]
        # Edge vector
        ex, ey = bx - ax, by - ay

        denom = rdx * ey - rdy * ex
        if abs(denom) < 1e-9:
            continue
        t = ((ax - wx) * ey - (ay - wy) * ex) / denom
        u = ((ax - wx) * rdy - (ay - wy) * rdx) / denom
        if t >= 0 and 0 <= u <= 1 and t < best_t:
            best_t = t
            best = (wx + rdx * t, wy + rdy * t)

    return best


# ── Gapped outline builders ──────────────────────────────────────


def _circle_with_gaps(
    shape, rect, gaps: list[tuple],
) -> str | None:
    """Build an SVG path for a circle with gaps at openings.

    Each gap is a pair of points on the circle.  The gap is the
    SHORTER arc between them (the opening facing the corridor).
    We normalize all angles to [0, 2π), mark gap intervals, sort
    them, and draw arcs between consecutive gap ends and starts.
    """
    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL
    d = shape._diameter(r)
    radius = d * CELL / 2
    ccx = px + pw / 2
    ccy = py + ph / 2

    TWO_PI = 2 * math.pi

    # Convert gap points to [0, 2π) angles, choosing the shorter
    # arc as the gap.
    gap_intervals: list[tuple[float, float]] = []
    for (ax, ay), (bx, by) in gaps:
        a1 = math.atan2(ay - ccy, ax - ccx) % TWO_PI
        a2 = math.atan2(by - ccy, bx - ccx) % TWO_PI
        # Ensure a1 is the smaller angle
        if a1 > a2:
            a1, a2 = a2, a1
        # Choose the shorter arc as the gap
        span = a2 - a1
        if span > math.pi:
            # The short arc wraps around 0 → gap is (a2, a1+2π)
            gap_intervals.append((a2, a1 + TWO_PI))
        else:
            gap_intervals.append((a1, a2))

    if not gap_intervals:
        return None

    # Sort gaps by start angle
    gap_intervals.sort()

    # Build draw segments: arcs between consecutive gaps.
    # Walk from the end of each gap to the start of the next.
    n = len(gap_intervals)
    draw_segments: list[tuple[float, float]] = []
    for i in range(n):
        gap_end = gap_intervals[i][1]
        next_gap_start = gap_intervals[(i + 1) % n][0]
        # Wrap: ensure we go forward around the circle
        if i == n - 1:
            next_gap_start += TWO_PI
        if next_gap_start <= gap_end:
            continue  # adjacent/overlapping gaps, no arc to draw
        draw_segments.append((gap_end, next_gap_start))

    if not draw_segments:
        return None

    path_parts = []
    for start_a, end_a in draw_segments:
        sx = ccx + radius * math.cos(start_a)
        sy = ccy + radius * math.sin(start_a)
        ex = ccx + radius * math.cos(end_a)
        ey = ccy + radius * math.sin(end_a)
        sweep = (end_a - start_a) % TWO_PI
        large = 1 if sweep > math.pi else 0
        path_parts.append(
            f'M{sx:.1f},{sy:.1f} '
            f'A{radius:.1f},{radius:.1f} 0 {large},1 '
            f'{ex:.1f},{ey:.1f}'
        )

    return f'<path d="{" ".join(path_parts)}"/>'


def _polygon_with_gaps(
    shape, rect, gaps: list[tuple],
) -> str | None:
    """Build an SVG path for a polygon with gaps at openings.

    Each gap is a pair of points on the polygon outline.  The
    outline draws TO the first point (break), skips the gap,
    then resumes FROM the second point.
    """
    verts = _polygon_vertices(shape, rect)
    if not verts:
        return None

    n = len(verts)

    # Build a list of (edge_index, t, point, role) where role is
    # 'break' or 'resume'.  For each gap, the point encountered
    # FIRST walking the polygon is the break, the second is resume.
    events = []  # (edge_idx, t, px, py, role, gap_idx)
    for gi, ((g1x, g1y), (g2x, g2y)) in enumerate(gaps):
        hits = []
        for gx, gy in [(g1x, g1y), (g2x, g2y)]:
            for i in range(n):
                ax, ay = verts[i]
                bx, by = verts[(i + 1) % n]
                t = _point_on_segment(ax, ay, bx, by, gx, gy)
                if t is not None:
                    hits.append((i, t, gx, gy))
                    break  # each gap point matches one edge
        if len(hits) == 2:
            # Order by polygon walk: compare (edge_idx, t)
            h0, h1 = hits
            if (h0[0], h0[1]) > (h1[0], h1[1]):
                h0, h1 = h1, h0
            events.append((*h0, 'break', gi))
            events.append((*h1, 'resume', gi))

    events.sort(key=lambda e: (e[0], e[1]))

    # Walk polygon edges, inserting breaks and resumes
    path_parts = []
    current_path: list[str] = []
    in_gap = False
    event_idx = 0

    for i in range(n):
        ax, ay = verts[i]
        bx, by = verts[(i + 1) % n]

        # Collect events on this edge
        edge_events = []
        while (event_idx < len(events)
               and events[event_idx][0] == i):
            edge_events.append(events[event_idx])
            event_idx += 1

        if not edge_events:
            if not in_gap:
                if not current_path:
                    current_path.append(f'M{ax:.1f},{ay:.1f}')
                current_path.append(f'L{bx:.1f},{by:.1f}')
            continue

        for ei, t, gx, gy, role, gi in edge_events:
            if role == 'break':
                # Draw to break point, then end segment
                if not in_gap:
                    if not current_path:
                        current_path.append(
                            f'M{ax:.1f},{ay:.1f}')
                    if abs(t) > 0.01:
                        current_path.append(
                            f'L{gx:.1f},{gy:.1f}')
                    if current_path:
                        path_parts.append(
                            " ".join(current_path))
                        current_path = []
                in_gap = True
            elif role == 'resume':
                # Start new segment from resume point
                in_gap = False
                current_path = [f'M{gx:.1f},{gy:.1f}']

        # After processing events, continue to edge end if not in gap
        if not in_gap:
            current_path.append(f'L{bx:.1f},{by:.1f}')

    if current_path:
        path_parts.append(" ".join(current_path))

    return f'<path d="{" ".join(path_parts)}"/>'


def _point_on_segment(
    ax: float, ay: float, bx: float, by: float,
    px: float, py: float, tol: float = 1.0,
) -> float | None:
    """If point (px, py) is within *tol* of segment A→B, return t."""
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-9:
        return None
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    if t < -0.01 or t > 1.01:
        return None
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    dist = math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)
    if dist <= tol:
        return max(0.0, min(1.0, t))
    return None


def _gap_on_edge(
    v1: tuple[float, float], v2: tuple[float, float],
    gap: tuple,
) -> bool:
    """Check if either gap point lies on the edge v1→v2."""
    (g1x, g1y), (g2x, g2y) = gap
    return (_point_on_segment(*v1, *v2, g1x, g1y) is not None
            or _point_on_segment(*v1, *v2, g2x, g2y) is not None)


# ── Smooth shape outlines ────────────────────────────────────────


def _room_svg_outline(room: "Room") -> str | None:
    """Return an SVG path for a room's smooth geometric outline.

    Returns None for shapes that should use the default tile-edge
    walls (e.g. RectShape or unknown shapes).  Coordinates are in
    pixel space (tile * CELL).
    """

    r = room.rect
    shape = room.shape

    # Pixel bounding box
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if isinstance(shape, CircleShape):
        cx = px + pw / 2
        cy = py + ph / 2
        d = shape._diameter(r)
        radius = d * CELL / 2
        return (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
            f'r="{radius:.1f}"/>'
        )

    if isinstance(shape, PillShape):
        d = shape._diameter(r)
        radius = d * CELL / 2.0
        if r.width >= r.height:
            bx = px
            by = py + (ph - d * CELL) / 2.0
            bw = pw
            bh = d * CELL
        else:
            bx = px + (pw - d * CELL) / 2.0
            by = py
            bw = d * CELL
            bh = ph
        return (
            f'<rect x="{bx:.1f}" y="{by:.1f}" '
            f'width="{bw:.1f}" height="{bh:.1f}" '
            f'rx="{radius:.1f}" ry="{radius:.1f}"/>'
        )

    if isinstance(shape, OctagonShape):
        clip = max(1, min(r.width, r.height) // 3) * CELL
        pts = [
            (px + clip, py),             # top-left flat
            (px + pw - clip, py),        # top-right flat
            (px + pw, py + clip),        # right-top flat
            (px + pw, py + ph - clip),   # right-bottom flat
            (px + pw - clip, py + ph),   # bottom-right flat
            (px + clip, py + ph),        # bottom-left flat
            (px, py + ph - clip),        # left-bottom flat
            (px, py + clip),             # left-top flat
        ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, TempleShape):
        pts = _temple_vertices(shape, r)
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, CrossShape):
        bar_w = max(2, r.width // 3) * CELL
        bar_h = max(2, r.height // 3) * CELL
        # Center of cross
        cx_tile = r.x + r.width // 2
        cy_tile = r.y + r.height // 2
        # Vertical bar left/right edges
        vl = (cx_tile - max(2, r.width // 3) // 2) * CELL
        vr = vl + bar_w
        # Horizontal bar top/bottom edges
        ht = (cy_tile - max(2, r.height // 3) // 2) * CELL
        hb = ht + bar_h
        # 12-point polygon tracing the + outline clockwise
        pts = [
            (vl, py),           # top-left of vertical bar
            (vr, py),           # top-right of vertical bar
            (vr, ht),           # inner corner: right arm top
            (px + pw, ht),      # right arm top-right
            (px + pw, hb),      # right arm bottom-right
            (vr, hb),           # inner corner: right arm bottom
            (vr, py + ph),      # bottom-right of vertical bar
            (vl, py + ph),      # bottom-left of vertical bar
            (vl, hb),           # inner corner: left arm bottom
            (px, hb),           # left arm bottom-left
            (px, ht),           # left arm top-left
            (vl, ht),           # inner corner: left arm top
        ]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        return f'<polygon points="{points}"/>'

    if isinstance(shape, HybridShape):
        return _hybrid_svg_outline(room)

    if isinstance(shape, CaveShape):
        return _cave_svg_outline(room)

    # RectShape or unknown — use tile-edge walls
    return None


def _cave_svg_outline(room: "Room") -> str | None:
    """Build an organic closed SVG path for a cave room (fill).

    Traces the contour of the cave's floor tiles and smooths it
    using Catmull-Rom → cubic Bézier conversion.  Always returns
    a closed path — used for the floor fill.  Wall rendering uses
    _cave_with_gaps instead so corridor openings become gaps.
    """
    tiles = room.floor_tiles()
    if not tiles:
        return None

    coords = _trace_cave_boundary_coords(tiles)
    if not coords or len(coords) < 4:
        return None

    return _smooth_closed_path(coords)


def _trace_cave_boundary_coords(
    tiles: set[tuple[int, int]],
) -> list[tuple[float, float]]:
    """Trace the outer contour of a set of tiles as pixel corners.

    Returns an ordered list of (x, y) corner points walking the
    boundary clockwise.  Uses Shapely's unary_union to handle the
    merge and extract the exterior ring.
    """
    from shapely.ops import unary_union

    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(Polygon([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = unary_union(boxes)
    if merged.is_empty:
        return []

    # Simplify to remove collinear tile-edge vertices
    simplified = merged.simplify(CELL * 0.35, preserve_topology=True)
    if hasattr(simplified, 'geoms'):
        simplified = max(simplified.geoms, key=lambda g: g.area)

    coords = list(simplified.exterior.coords)
    if coords and coords[-1] == coords[0]:
        coords = coords[:-1]
    return coords


def _smooth_closed_path(
    coords: list[tuple[float, float]],
) -> str:
    """Build an SVG path (closed, centripetal Catmull-Rom → cubic bezier).

    Uses centripetal parameterization (α=0.5) which eliminates
    cusps and self-intersections that uniform Catmull-Rom produces
    when control points are unevenly spaced (common after jitter).
    """
    n = len(coords)
    parts = [f'M{coords[0][0]:.1f},{coords[0][1]:.1f}']
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        p3 = coords[(i + 2) % n]
        c1x, c1y, c2x, c2y = _centripetal_bezier_cps(
            p0, p1, p2, p3,
        )
        parts.append(
            f'C{c1x:.1f},{c1y:.1f} '
            f'{c2x:.1f},{c2y:.1f} '
            f'{p2[0]:.1f},{p2[1]:.1f}'
        )
    parts.append('Z')
    return f'<path d="{" ".join(parts)}"/>'


def _centripetal_bezier_cps(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    alpha: float = 0.5,
) -> tuple[float, float, float, float]:
    """Compute cubic Bézier control points for centripetal Catmull-Rom.

    Given four sequential Catmull-Rom points, returns (c1x, c1y,
    c2x, c2y) — the two interior control points of the cubic
    Bézier segment between *p1* and *p2*.

    *alpha* = 0.5 is centripetal (eliminates cusps/loops),
    0.0 is uniform (classic), 1.0 is chordal.
    """
    # Knot intervals: t_{i+1} - t_i = |P_{i+1} - P_i|^alpha
    d01 = max(math.hypot(p1[0] - p0[0], p1[1] - p0[1]) ** alpha,
              1e-6)
    d12 = max(math.hypot(p2[0] - p1[0], p2[1] - p1[1]) ** alpha,
              1e-6)
    d23 = max(math.hypot(p3[0] - p2[0], p3[1] - p2[1]) ** alpha,
              1e-6)
    # Tangent at p1 for the segment p1→p2 (Barry-Goldman):
    #   m1 = d12 * [(p1-p0)/d01 - (p2-p0)/(d01+d12) + (p2-p1)/d12]
    m1x = d12 * ((p1[0] - p0[0]) / d01
                  - (p2[0] - p0[0]) / (d01 + d12)
                  + (p2[0] - p1[0]) / d12)
    m1y = d12 * ((p1[1] - p0[1]) / d01
                  - (p2[1] - p0[1]) / (d01 + d12)
                  + (p2[1] - p1[1]) / d12)
    # Tangent at p2:
    #   m2 = d12 * [(p2-p1)/d12 - (p3-p1)/(d12+d23) + (p3-p2)/d23]
    m2x = d12 * ((p2[0] - p1[0]) / d12
                  - (p3[0] - p1[0]) / (d12 + d23)
                  + (p3[0] - p2[0]) / d23)
    m2y = d12 * ((p2[1] - p1[1]) / d12
                  - (p3[1] - p1[1]) / (d12 + d23)
                  + (p3[1] - p2[1]) / d23)
    # Bézier control points
    c1x = p1[0] + m1x / 3
    c1y = p1[1] + m1y / 3
    c2x = p2[0] - m2x / 3
    c2y = p2[1] - m2y / 3
    return c1x, c1y, c2x, c2y


def _smooth_open_path(
    coords: list[tuple[float, float]],
) -> str:
    """Build an SVG path (open, centripetal Catmull-Rom → cubic bezier).

    For open curves, endpoints use duplicated neighbors as the
    virtual p0/p3 so the curve passes exactly through them.
    Uses centripetal parameterization (α=0.5) to match closed paths.
    """
    n = len(coords)
    if n < 2:
        return ""
    parts = [f'M{coords[0][0]:.1f},{coords[0][1]:.1f}']
    for i in range(n - 1):
        p0 = coords[i - 1] if i > 0 else coords[i]
        p1 = coords[i]
        p2 = coords[i + 1]
        p3 = coords[i + 2] if i + 2 < n else coords[i + 1]
        c1x, c1y, c2x, c2y = _centripetal_bezier_cps(
            p0, p1, p2, p3,
        )
        parts.append(
            f'C{c1x:.1f},{c1y:.1f} '
            f'{c2x:.1f},{c2y:.1f} '
            f'{p2[0]:.1f},{p2[1]:.1f}'
        )
    return " ".join(parts)


def _collect_cave_region(level: "Level") -> set[tuple[int, int]]:
    """Collect all tiles belonging to the unified cave region.

    Seeds the flood-fill with every floor tile belonging to a
    CaveShape room, then expands through adjacent walkable
    corridor tiles.  A corridor is considered part of the cave
    region if it is reachable from any cave room via a chain of
    walkable (FLOOR/WATER/GRASS) tiles that includes at least
    one corridor step — i.e. any corridor connected (directly or
    transitively) to a cave room is pulled in.
    """
    walkable = (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)

    # Seed with cave room floor tiles
    seed: set[tuple[int, int]] = set()
    for room in level.rooms:
        if isinstance(room.shape, CaveShape):
            seed |= room.floor_tiles()
    if not seed:
        return set()

    # Flood through corridor tiles adjacent to the region
    region: set[tuple[int, int]] = set(seed)
    frontier: list[tuple[int, int]] = list(seed)
    while frontier:
        x, y = frontier.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in region:
                continue
            nb = level.tile_at(nx, ny)
            if not nb or nb.terrain not in walkable:
                continue
            # Only expand into corridor tiles — we don't want to
            # absorb adjacent non-cave rooms.
            if not nb.is_corridor:
                continue
            region.add((nx, ny))
            frontier.append((nx, ny))
    return region


def _build_cave_polygon(
    tiles: set[tuple[int, int]],
):
    """Union tile squares into a Shapely Polygon or MultiPolygon.

    Returns None for empty input.  Exteriors come out CCW and
    holes CW (Shapely default), which the outward-normal jitter
    relies on for direction.
    """
    if not tiles:
        return None
    boxes = []
    for tx, ty in tiles:
        px, py = tx * CELL, ty * CELL
        boxes.append(Polygon([
            (px, py), (px + CELL, py),
            (px + CELL, py + CELL), (px, py + CELL),
        ]))
    merged = unary_union(boxes)
    if merged.is_empty:
        return None
    return merged


def _densify_ring(
    coords: list[tuple[float, float]],
    step: float,
) -> list[tuple[float, float]]:
    """Insert synthetic vertices along long edges.

    Walks *coords* (assumed non-repeating, ring closes implicitly)
    and inserts intermediate points every ~*step* pixels on any
    edge longer than *step*.  Preserves the original corners so
    the tile-edge polygon's shape is not distorted before jitter.
    """
    if len(coords) < 2:
        return list(coords)
    n = len(coords)
    out: list[tuple[float, float]] = []
    for i in range(n):
        a = coords[i]
        b = coords[(i + 1) % n]
        out.append(a)
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        dist = math.hypot(dx, dy)
        if dist <= step:
            continue
        n_sub = int(dist // step)
        for k in range(1, n_sub + 1):
            t = k / (n_sub + 1)
            out.append((a[0] + dx * t, a[1] + dy * t))
    return out


def _jitter_ring_outward(
    coords: list[tuple[float, float]],
    floor_poly,
    rng: random.Random,
    is_hole: bool = False,
    direction_poly=None,
) -> list[tuple[float, float]]:
    """Push each control point outward along its outward normal.

    *coords* is a non-repeating ring (no duplicated closing point).
    *floor_poly* is the hard containment invariant — the jittered
    result is guaranteed to stay outside this polygon (so floor
    tiles always remain inside the final wall ring).
    *direction_poly* is the shape whose boundary *coords* actually
    lies on; it is used to decide which perpendicular is "outward"
    when the vertices live on a buffered ring that is some distance
    from *floor_poly*.  Defaults to *floor_poly* for backwards
    compatibility.

    Jitter magnitude combines a base random offset, corner-aware
    damping, and a sinusoidal S-curve modulation keyed to
    arc-length position for organic Dyson-style undulation.
    The result is clamped to half the local edge length so two
    adjacent jittered points can never cross each other.
    """
    n = len(coords)
    if n < 3:
        return list(coords)

    from shapely.geometry import Point as ShPoint

    if direction_poly is None:
        direction_poly = floor_poly

    # Pre-compute cumulative arc-length for S-curve modulation.
    arc_lengths = [0.0]
    for i in range(n):
        a = coords[i]
        b = coords[(i + 1) % n]
        arc_lengths.append(
            arc_lengths[-1] + math.hypot(b[0] - a[0], b[1] - a[1])
        )
    total_arc = max(arc_lengths[-1], 1e-6)
    # S-curve parameters: frequency scales with perimeter so
    # larger caves get more undulations.  Phase is random per
    # ring so each wall segment looks different.
    # Low frequency → fewer, bolder lobes (Dyson style).
    scurve_freq = max(4.0, total_arc / (CELL * 2.0))
    scurve_phase = rng.uniform(0, 2 * math.pi)
    # Second harmonic at ~1.7× frequency for organic variation
    # (avoids the mechanical look of a pure single sine wave).
    scurve_freq2 = scurve_freq * 1.7
    scurve_phase2 = rng.uniform(0, 2 * math.pi)
    # Tangential wave — shifts points along the wall to create
    # true S-curves, not just in/out wobble.
    tang_freq = scurve_freq * 0.8
    tang_phase = rng.uniform(0, 2 * math.pi)

    out: list[tuple[float, float]] = []
    for i in range(n):
        prev_p = coords[(i - 1) % n]
        cur_p = coords[i]
        next_p = coords[(i + 1) % n]
        # Average of incoming and outgoing edge directions
        e1x, e1y = cur_p[0] - prev_p[0], cur_p[1] - prev_p[1]
        e2x, e2y = next_p[0] - cur_p[0], next_p[1] - cur_p[1]
        tx = e1x + e2x
        ty = e1y + e2y
        tlen = math.hypot(tx, ty)
        if tlen < 1e-6:
            out.append(cur_p)
            continue
        tx /= tlen
        ty /= tlen
        # The tangent has two perpendiculars; "outward" is the one
        # that leaves the floor polygon.  Probe both and pick the
        # one whose small test offset lands outside.  This is
        # orientation-agnostic — works whether Shapely returned the
        # ring CW or CCW, and whether this is an exterior or a hole.
        cand_a = (ty, -tx)
        cand_b = (-ty, tx)
        probe = 0.5
        a_outside = not direction_poly.contains(
            ShPoint(cur_p[0] + cand_a[0] * probe,
                    cur_p[1] + cand_a[1] * probe)
        )
        if a_outside:
            nx, ny = cand_a
        else:
            nx, ny = cand_b
        # Sub-tile outward jitter, deterministic via rng order.
        # Magnitude chosen so the wobble amplitude reads at
        # full-map zoom while staying within the one-tile hatching
        # band that Dyson leaves around cave boundaries.  Clamp to
        # half the local edge length so two adjacent jittered
        # points cannot cross each other and the ring stays simple.
        e1_len = math.hypot(e1x, e1y)
        e2_len = math.hypot(e2x, e2y)
        # Cap to prevent ring self-intersection.  Sine-based
        # displacement moves adjacent points similarly, so a
        # generous cap is safe.
        local_cap = max(1.0, min(e1_len, e2_len) * 0.85)
        # Corner-aware damping: reduce jitter at sharp corners
        # where knots are most likely to form.  Compute the
        # cosine of the angle between incoming/outgoing edges;
        # a sharp concave corner (cos → −1) gets damped to ~30%,
        # a straight edge (cos → 1) gets full magnitude.
        if e1_len > 1e-6 and e2_len > 1e-6:
            cos_angle = (
                (e1x * e2x + e1y * e2y) / (e1_len * e2_len)
            )
            # Map cos_angle from [-1, 1] to damping [0.3, 1.0]
            corner_damp = 0.3 + 0.7 * (cos_angle + 1) / 2
        else:
            corner_damp = 1.0
        # S-curve modulation: the sine wave is the PRIMARY
        # displacement; random noise is just a small perturbation.
        # This ensures the wall boundary visibly undulates in a
        # Dyson hand-drawn style rather than looking randomly
        # jittered around a straight edge.
        arc_frac = arc_lengths[i] / total_arc
        theta = 2 * math.pi * scurve_freq * arc_frac
        wave = math.sin(theta + scurve_phase)
        wave2 = math.sin(
            2 * math.pi * scurve_freq2 * arc_frac + scurve_phase2
        )
        # Combined wave: primary + 40% second harmonic
        combined_wave = wave + 0.4 * wave2
        # Constant outward base + sinusoidal undulation + noise
        base_offset = CELL * 0.15
        wave_amp = CELL * 0.25
        noise = CELL * rng.uniform(-0.08, 0.08)
        mag = (base_offset + wave_amp * combined_wave
               + noise) * corner_damp
        mag = min(max(mag, CELL * 0.05), local_cap)
        # Tangential shift — small slide along the wall direction
        # to break up the pure-normal look.  Kept small relative
        # to step to avoid ring self-intersection.
        tang_wave = math.sin(
            2 * math.pi * tang_freq * arc_frac + tang_phase
        )
        tang_shift = CELL * 0.08 * tang_wave * corner_damp
        px = cur_p[0] + nx * mag + tx * tang_shift
        py = cur_p[1] + ny * mag + ty * tang_shift
        # Safety: at deeply concave vertices the outward ray can
        # still re-enter the polygon at distance.  Shrink until out.
        attempts = 0
        while floor_poly.contains(ShPoint(px, py)) and attempts < 4:
            mag *= 0.5
            px = cur_p[0] + nx * mag
            py = cur_p[1] + ny * mag
            attempts += 1
        if attempts == 4 and floor_poly.contains(ShPoint(px, py)):
            # Give up — fall back to the unjittered vertex (on the
            # boundary, so the floor still stays enclosed).
            px, py = cur_p
        out.append((px, py))
    return out


def _ring_to_subpath(
    coords: list[tuple[float, float]],
) -> str:
    """Smooth a closed ring into a Catmull-Rom cubic-Bézier subpath.

    Returns just the path data string (M…C…Z), without the
    <path> wrapper, so multiple rings can be concatenated into a
    single <path> element.
    """
    if len(coords) < 3:
        return ""
    smoothed = _smooth_closed_path(coords)
    # _smooth_closed_path wraps in <path d="…"/>; unwrap.
    m = re.search(r'd="([^"]+)"', smoothed)
    return m.group(1) if m else ""


def _build_cave_wall_geometry(
    level: "Level", rng: random.Random,
):
    """Build the unified cave region wall geometry.

    Returns a tuple ``(svg_path, wall_polygon, tiles)``:
      * ``svg_path`` is the smoothed ``<path>`` element for the
        wall stroke (one subpath per ring).
      * ``wall_polygon`` is a Shapely Polygon/MultiPolygon whose
        rings match the jittered wall path — used as the clip
        boundary for floor fill and grid, so both extend out to
        (and are cut by) the same curve the wall stroke follows.
      * ``tiles`` is the set of cave-region tiles (rooms +
        connected corridors) so callers can skip per-tile
        rendering for them.

    Returns ``(None, None, empty_set)`` when the level has no cave
    region.

    Collects every cave-region tile, unions into a Shapely geometry,
    simplifies the tile-edge staircase with Douglas-Peucker, then
    for every ring emits one Catmull-Rom smoothed subpath whose
    control points are densified and pushed outward along each
    vertex's outward normal so the floor polygon stays strictly
    enclosed by the wall ring.
    """
    tiles = _collect_cave_region(level)
    if not tiles:
        return None, None, set()
    geom = _build_cave_polygon(tiles)
    if geom is None or geom.is_empty:
        return None, None, tiles

    # Normalize into a list of Polygons
    polys: list = []
    if hasattr(geom, 'geoms'):
        polys = [g for g in geom.geoms if not g.is_empty]
    else:
        polys = [geom]
    if not polys:
        return None, None, tiles

    # Expand the tile-edge polygon outward with Shapely's round-
    # join buffer.  This does two things at once:
    #   1. Every 90° stairstep corner becomes a quarter-circle
    #      arc — no pronounced L silhouettes in the wall.
    #   2. The wall gains ~0.4 CELL of slack into the void, so
    #      the subsequent outward jitter has room to bulge without
    #      immediately bumping into adjacent regions.
    # The outward jitter still uses the UNBUFFERED ``poly`` for the
    # containment safety check, so no floor tile can end up outside
    # the final wall ring no matter how the jitter lands.
    buffer_r = CELL * 0.3
    # Light simplification after buffering to remove collinear
    # points introduced by adjacent arc segments while keeping the
    # arcs themselves intact.
    simplify_tol = CELL * 0.15
    step = CELL * 0.8
    subpaths: list[str] = []
    wall_polys: list[Polygon] = []
    for poly in polys:
        inflated = poly.buffer(
            buffer_r, join_style='round', quad_segs=8,
        )
        if inflated.is_empty:
            continue
        # Buffering a MultiPolygon may fuse or split into multiple
        # parts; keep the largest component for this source poly.
        if hasattr(inflated, 'geoms'):
            inflated = max(inflated.geoms, key=lambda g: g.area)
        simp = inflated.simplify(
            simplify_tol, preserve_topology=True,
        )
        simp = _shapely_orient(simp, sign=1.0)
        if simp.is_empty or not hasattr(simp, 'exterior'):
            continue
        # Exterior ring (CCW)
        ext = list(simp.exterior.coords)
        if ext and ext[0] == ext[-1]:
            ext = ext[:-1]
        ext_d = _densify_ring(ext, step)
        ext_j = _jitter_ring_outward(
            ext_d, poly, rng, is_hole=False,
            direction_poly=simp,
        )
        s = _ring_to_subpath(ext_j)
        if s:
            subpaths.append(s)
        # Holes (CW).  Buffer the source polygon's holes INWARD
        # (i.e. use poly.interiors directly — they are already
        # rings, and we want the wall around each hole to match
        # the outward buffer semantics when viewed from inside).
        jittered_holes: list[list[tuple[float, float]]] = []
        for hole in simp.interiors:
            h = list(hole.coords)
            if h and h[0] == h[-1]:
                h = h[:-1]
            h_d = _densify_ring(h, step)
            h_j = _jitter_ring_outward(
                h_d, poly, rng, is_hole=True,
                direction_poly=simp,
            )
            s = _ring_to_subpath(h_j)
            if s:
                subpaths.append(s)
                jittered_holes.append(h_j)
        # Matching polygon for clip/fill, built from the same
        # jittered rings so floor + grid align exactly with the
        # wall stroke.
        if len(ext_j) >= 3:
            wp = Polygon(ext_j, holes=jittered_holes)
            if wp.is_valid and not wp.is_empty:
                wall_polys.append(wp)
            else:
                # Fix tiny self-intersections from aggressive jitter.
                wp_fixed = wp.buffer(0)
                if not wp_fixed.is_empty:
                    wall_polys.append(wp_fixed)

    if not subpaths:
        return None, None, tiles
    svg_path = f'<path d="{" ".join(subpaths)}"/>'
    wall_polygon = (
        unary_union(wall_polys) if wall_polys else None
    )
    return svg_path, wall_polygon, tiles


def _cave_region_walls(
    level: "Level", rng: random.Random,
) -> str | None:
    """Return only the SVG wall path for a cave region.

    Thin wrapper around :func:`_build_cave_wall_geometry` kept for
    the unit tests and any caller that does not need the clip
    polygon.
    """
    svg_path, _poly, _tiles = _build_cave_wall_geometry(level, rng)
    return svg_path


def _hybrid_svg_outline(room: "Room") -> str | None:
    """Build an SVG path for a hybrid room.

    Traces the outer contour combining the curved sub-shape on
    one side and straight lines on the rect side.
    """

    shape = room.shape
    if not isinstance(shape, HybridShape):
        return None

    r = room.rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if shape.split == "vertical":
        mid = px + (r.width // 2) * CELL
        # Left sub-shape occupies [px, mid], right occupies [mid, px+pw]
        left_path = _half_outline(
            shape.left, px, py, mid - px, ph, side="left",
        )
        right_path = _half_outline(
            shape.right, mid, py, px + pw - mid, ph, side="right",
        )
        if left_path and right_path:
            # Combine: start top-left, trace left outer edge down,
            # then right outer edge back up
            return (
                f'<path d="'
                f'M{mid:.1f},{py:.1f} '  # top-mid
                f'{left_path} '           # left side → bottom-mid
                f'{right_path} '          # right side → top-mid
                f'Z"/>'
            )
    else:
        mid = py + (r.height // 2) * CELL
        top_path = _half_outline(
            shape.left, px, py, pw, mid - py, side="top",
        )
        bottom_path = _half_outline(
            shape.right, px, mid, pw, py + ph - mid, side="bottom",
        )
        if top_path and bottom_path:
            return (
                f'<path d="'
                f'M{px:.1f},{mid:.1f} '
                f'{top_path} '
                f'{bottom_path} '
                f'Z"/>'
            )

    return None


def _half_outline(
    sub_shape: "RoomShape",
    px: float, py: float, pw: float, ph: float,
    side: str,
) -> str | None:
    """Return SVG path commands for one half of a hybrid outline.

    *side* is which outer edge this half contributes:
    - "left": traces top→left→bottom (clockwise down the left)
    - "right": traces bottom→right→top (clockwise up the right)
    - "top": traces left→top→right (clockwise across the top)
    - "bottom": traces right→bottom→left (clockwise across bottom)
    """


    if isinstance(sub_shape, RectShape):
        if side == "left":
            # top-mid → top-left → bottom-left → bottom-mid
            return (
                f'L{px:.1f},{py:.1f} '
                f'L{px:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            # bottom-mid → bottom-right → top-right → top-mid
            return (
                f'L{px + pw:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            # left-mid → top-left → top-right → right-mid
            return (
                f'L{px:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            # right-mid → bottom-right → bottom-left → left-mid
            return (
                f'L{px + pw:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    if isinstance(sub_shape, CircleShape):
        cx = px + pw / 2
        cy = py + ph / 2
        tw = int(round(pw / CELL))
        th = int(round(ph / CELL))
        d = sub_shape._diameter(Rect(0, 0, tw, th))
        r = d * CELL / 2
        # SVG arc: A rx ry x-rotation large-arc sweep x y
        if side == "left":
            # Arc from (cx, cy-r) clockwise down to (cx, cy+r)
            return (
                f'L{cx:.1f},{cy - r:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx:.1f},{cy + r:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            return (
                f'L{cx:.1f},{cy + r:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,0 '
                f'{cx:.1f},{cy - r:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            return (
                f'L{cx - r:.1f},{cy:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,1 '
                f'{cx + r:.1f},{cy:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            return (
                f'L{cx + r:.1f},{cy:.1f} '
                f'A{r:.1f},{r:.1f} 0 0,1 '
                f'{cx - r:.1f},{cy:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    if isinstance(sub_shape, OctagonShape):

        # Approximate clip from the tile-based algorithm
        tw = int(pw / CELL)
        th = int(ph / CELL)
        clip = max(1, min(tw, th) // 3) * CELL
        if side == "left":
            return (
                f'L{px + clip:.1f},{py:.1f} '
                f'L{px:.1f},{py + clip:.1f} '
                f'L{px:.1f},{py + ph - clip:.1f} '
                f'L{px + clip:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "right":
            return (
                f'L{px + pw - clip:.1f},{py + ph:.1f} '
                f'L{px + pw:.1f},{py + ph - clip:.1f} '
                f'L{px + pw:.1f},{py + clip:.1f} '
                f'L{px + pw - clip:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f}'
            )
        if side == "top":
            return (
                f'L{px:.1f},{py + clip:.1f} '
                f'L{px + clip:.1f},{py:.1f} '
                f'L{px + pw - clip:.1f},{py:.1f} '
                f'L{px + pw:.1f},{py + clip:.1f} '
                f'L{px + pw:.1f},{py + ph:.1f}'
            )
        if side == "bottom":
            return (
                f'L{px + pw:.1f},{py + ph - clip:.1f} '
                f'L{px + pw - clip:.1f},{py + ph:.1f} '
                f'L{px + clip:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph - clip:.1f} '
                f'L{px:.1f},{py:.1f}'
            )

    return None


def _room_shadow_svg(room: "Room") -> str:
    """Return an SVG element for a room's shadow.

    Reuses _room_svg_outline for non-rect shapes, applying fill
    and a (3,3) offset.  Rect rooms get a simple rect shadow.
    """
    outline = _room_svg_outline(room)
    if outline:
        el = outline.replace(
            '/>', f' fill="{INK}" opacity="0.08"/>')
        return f'<g transform="translate(3,3)">{el}</g>'

    # Rect — default rectangle shadow
    r = room.rect
    px, py = r.x * CELL + 3, r.y * CELL + 3
    pw, ph = r.width * CELL, r.height * CELL
    return (
        f'<rect x="{px}" y="{py}" '
        f'width="{pw}" height="{ph}" '
        f'fill="{INK}" opacity="0.08"/>'
    )


# ── Layer renderers ──────────────────────────────────────────────

def _render_room_shadows(svg: list[str], level: "Level") -> None:
    """Subtle offset shadow for rooms (shape-aware)."""
    for room in level.rooms:
        svg.append(_room_shadow_svg(room))


def _render_corridor_shadows(svg: list[str], level: "Level") -> None:
    """Per-tile offset shadow for corridor and door tiles."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.is_corridor or _is_door(level, x, y)):
                continue
            px, py = x * CELL + 3, y * CELL + 3
            svg.append(
                f'<rect x="{px}" y="{py}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{INK}" opacity="0.08"/>')


def _render_corridor_hatching(
    svg: list[str], level: "Level", seed: int,
) -> None:
    """Hatch VOID tiles adjacent to corridors (one tile each side).

    Reuses the same visual style as room hatching — grey underlay,
    stones, and section-partitioned hatch lines.
    """

    rng = random.Random(seed + 7)

    # Collect VOID tiles that border a corridor or door tile
    hatch_tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.is_corridor or _is_door(level, x, y)):
                continue
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if not level.in_bounds(nx, ny):
                    continue
                nb = level.tiles[ny][nx]
                if (nb.terrain == Terrain.VOID
                        and not nb.is_corridor):
                    hatch_tiles.add((nx, ny))

    if not hatch_tiles:
        return

    min_stroke = 1.0
    max_stroke = 1.8
    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gx, gy in sorted(hatch_tiles):
        # Grey underlay tile
        tile_fills.append(
            f'<rect x="{gx * CELL}" y="{gy * CELL}" '
            f'width="{CELL}" height="{CELL}" '
            f'fill="{HATCH_UNDERLAY}"/>')

        # Scatter 0-2 stones
        n_stones = rng.choices(
            [0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        for _ in range(n_stones):
            sx = (gx + rng.uniform(0.15, 0.85)) * CELL
            sy = (gy + rng.uniform(0.15, 0.85)) * CELL
            rx = rng.uniform(2, CELL * 0.25)
            ry = rng.uniform(2, CELL * 0.2)
            angle = rng.uniform(0, 180)
            sw = rng.uniform(1.2, 2.0)
            hatch_stones.append(
                f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'transform="rotate({angle:.0f},'
                f'{sx:.1f},{sy:.1f})" '
                f'fill="{HATCH_UNDERLAY}" stroke="#666666" '
                f'stroke-width="{sw:.1f}"/>')

        # Perlin-displaced cluster anchor
        nr = CELL * 0.1
        adx = _noise.pnoise2(gx * 0.5, gy * 0.5, base=1) * nr
        ady = _noise.pnoise2(gx * 0.5, gy * 0.5, base=2) * nr
        anchor = ((gx + 0.5) * CELL + adx,
                  (gy + 0.5) * CELL + ady)

        corners = [
            (gx * CELL, gy * CELL),
            ((gx + 1) * CELL, gy * CELL),
            ((gx + 1) * CELL, (gy + 1) * CELL),
            (gx * CELL, (gy + 1) * CELL),
        ]

        pts = _pick_section_points(corners, anchor, CELL, rng)
        sections = _build_sections(anchor, pts, corners)

        for i, section in enumerate(sections):
            if section.is_empty or section.area < 1:
                continue
            if i == 0:
                angle = math.atan2(
                    pts[1][1] - pts[0][1],
                    pts[1][0] - pts[0][0])
            else:
                angle = rng.uniform(0, math.pi)

            bounds = section.bounds
            diag = math.hypot(
                bounds[2] - bounds[0], bounds[3] - bounds[1])
            spacing = CELL * 0.20
            n_lines = max(3, int(diag / spacing))

            for j in range(n_lines):
                offset = (j - (n_lines - 1) / 2) * spacing
                scx = section.centroid.x
                scy = section.centroid.y
                perp_x = math.cos(angle + math.pi / 2) * offset
                perp_y = math.sin(angle + math.pi / 2) * offset
                line = LineString([
                    (scx + perp_x - math.cos(angle) * diag,
                     scy + perp_y - math.sin(angle) * diag),
                    (scx + perp_x + math.cos(angle) * diag,
                     scy + perp_y + math.sin(angle) * diag),
                ])
                clipped = section.intersection(line)
                if (clipped.is_empty
                        or not isinstance(clipped, LineString)):
                    continue
                p1, p2 = list(clipped.coords)
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
                lsw = rng.uniform(min_stroke, max_stroke)
                hatch_lines.append(
                    f'<line x1="{p1[0]:.1f}" '
                    f'y1="{p1[1]:.1f}" '
                    f'x2="{p2[0]:.1f}" '
                    f'y2="{p2[1]:.1f}" '
                    f'stroke="{INK}" '
                    f'stroke-width="{lsw:.2f}" '
                    f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')



def _wobbly_grid_seg(
    rng: random.Random, x0: float, y0: float,
    x1: float, y1: float, noise_x: float, noise_y: float,
    base: int,
) -> str:
    """Build one wobbly grid segment with optional gap."""
    wobble = CELL * 0.05
    n_sub = 5
    dx, dy = x1 - x0, y1 - y0
    pts = []
    for i in range(n_sub + 1):
        t = i / n_sub
        lx = x0 + dx * t + _noise.pnoise2(
            noise_x + t * 0.5, noise_y, base=base) * wobble
        ly = y0 + dy * t + _noise.pnoise2(
            noise_x + t * 0.5, noise_y, base=base + 4) * wobble
        # Keep wobble perpendicular only: for vertical lines wobble
        # x, for horizontal wobble y
        if abs(dx) > abs(dy):
            # Mostly horizontal — wobble y only
            lx = x0 + dx * t
            ly = y0 + dy * t + _noise.pnoise2(
                noise_x + t * 0.5, noise_y, base=base) * wobble
        else:
            # Mostly vertical — wobble x only
            lx = x0 + dx * t + _noise.pnoise2(
                noise_x + t * 0.5, noise_y, base=base) * wobble
            ly = y0 + dy * t
        pts.append((lx, ly))
    gap_pos = rng.randint(1, n_sub - 1)
    seg = f'M{pts[0][0]:.1f},{pts[0][1]:.1f}'
    for i in range(1, len(pts)):
        if i == gap_pos and rng.random() < 0.25:
            seg += f' M{pts[i][0]:.1f},{pts[i][1]:.1f}'
        else:
            seg += f' L{pts[i][0]:.1f},{pts[i][1]:.1f}'
    return seg


# Per-theme multipliers for floor detail density.
# Values > 1.0 increase cracks, stones, and scratches.
_DETAIL_SCALE: dict[str, float] = {
    "dungeon": 1.0,
    "crypt":   2.0,
    "cave":    2.0,
    "sewer":   1.0,
    "castle":  0.8,
    "forest":  0.6,
    "abyss":   1.5,
}

# Per-theme probabilities for thematic detail types.
# Each value is the probability of that detail appearing per tile.
_THEMATIC_DETAIL_PROBS: dict[str, dict[str, float]] = {
    "dungeon": {"web": 0.03, "bones": 0.02, "skull": 0.01},
    "crypt":   {"web": 0.08, "bones": 0.10, "skull": 0.06},
    "cave":    {"web": 0.12, "bones": 0.04, "skull": 0.02},
    "sewer":   {"web": 0.06, "bones": 0.03, "skull": 0.01},
    "castle":  {"web": 0.02, "bones": 0.01, "skull": 0.005},
    "forest":  {"web": 0.04, "bones": 0.01, "skull": 0.005},
    "abyss":   {"web": 0.05, "bones": 0.08, "skull": 0.10},
}
_THEMATIC_DEFAULT: dict[str, float] = {
    "web": 0.03, "bones": 0.02, "skull": 0.01,
}


def _tile_detail(
    rng: random.Random, x: int, y: int, seed: int,
    cracks: list[str], stones: list[str], scratches: list[str],
    detail_scale: float = 1.0,
    theme: str = "dungeon",
) -> None:
    """Generate floor detail (cracks, stones, scratches) for one tile."""
    px, py = x * CELL, y * CELL
    is_cave = theme == "cave"

    # Caves: more cracks, fewer scratches, bigger stones
    crack_prob = 0.32 if is_cave else 0.08
    scratch_prob = 0.01 if is_cave else 0.05
    stone_prob = 0.10 if is_cave else 0.06
    cluster_prob = 0.06 if is_cave else 0.03
    stone_scale = 1.8 if is_cave else 1.0

    roll = rng.random()
    if roll < crack_prob * detail_scale:
        # Crack line from a tile corner into the tile interior.
        # The tile grid edges complete the triangle visually.
        corner = rng.randint(0, 3)
        s1 = rng.uniform(CELL * 0.15, CELL * 0.4)
        s2 = rng.uniform(CELL * 0.15, CELL * 0.4)
        if corner == 0:      # top-left
            cracks.append(f'{px + s1},{py} {px},{py + s2}')
        elif corner == 1:    # top-right
            cracks.append(
                f'{px + CELL - s1},{py} {px + CELL},{py + s2}')
        elif corner == 2:    # bottom-left
            cracks.append(
                f'{px + s1},{py + CELL} {px},{py + CELL - s2}')
        else:                # bottom-right
            cracks.append(
                f'{px + CELL - s1},{py + CELL} '
                f'{px + CELL},{py + CELL - s2}')
    elif roll < crack_prob * detail_scale + scratch_prob * detail_scale:
        scratches.append(_y_scratch(rng, px, py, x, y, seed))

    if rng.random() < stone_prob * detail_scale:
        stones.append(_floor_stone(rng, px, py, scale=stone_scale))

    if rng.random() < cluster_prob * detail_scale:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        for _ in range(3):
            sx = cx + rng.uniform(-CELL * 0.2, CELL * 0.2)
            sy = cy + rng.uniform(-CELL * 0.2, CELL * 0.2)
            scale = rng.uniform(0.5, 1.3) * stone_scale
            rx = rng.uniform(2, CELL * 0.15) * scale
            ry = rng.uniform(2, CELL * 0.12) * scale
            angle = rng.uniform(0, 180)
            sw = rng.uniform(1.2, 2.0)
            stones.append(
                f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                f'rx="{rx:.1f}" ry="{ry:.1f}" '
                f'transform="rotate({angle:.0f},'
                f'{sx:.1f},{sy:.1f})" '
                f'fill="{FLOOR_STONE_FILL}" '
                f'stroke="{FLOOR_STONE_STROKE}" '
                f'stroke-width="{sw:.1f}"/>')


def _emit_detail(
    svg: list[str],
    cracks: list[str], stones: list[str], scratches: list[str],
) -> None:
    """Append accumulated floor detail elements to the SVG."""
    if cracks:
        lines = "".join(
            f'<line x1="{c.split()[0].split(",")[0]}" '
            f'y1="{c.split()[0].split(",")[1]}" '
            f'x2="{c.split()[1].split(",")[0]}" '
            f'y2="{c.split()[1].split(",")[1]}" '
            f'stroke="{INK}" stroke-width="0.5" '
            f'stroke-linecap="round"/>'
            for c in cracks
        )
        svg.append(f'<g opacity="0.5">{lines}</g>')
    if scratches:
        svg.append(
            f'<g class="y-scratch" opacity="0.45">'
            f'{"".join(scratches)}</g>')
    if stones:
        svg.append(f'<g opacity="0.8">{"".join(stones)}</g>')


def _tile_thematic_detail(
    rng: random.Random, x: int, y: int,
    level: "Level",
    probs: dict[str, float],
    webs: list[str], bones: list[str], skulls: list[str],
) -> None:
    """Generate thematic details (webs, bones, skulls) for one tile.

    Webs only appear in corners adjacent to walls.
    Bones and skulls can appear on any floor tile.
    Only processes actual floor tiles (not walls inside room rects).
    """
    tile = level.tiles[y][x]
    if tile.terrain != Terrain.FLOOR:
        return
    px, py = x * CELL, y * CELL

    # Webs — only in corners that touch walls on both sides
    if rng.random() < probs.get("web", 0):
        wall_corners = []
        # Check each corner: needs wall on both adjacent sides
        if not _is_floor(level, x, y - 1) and \
                not _is_floor(level, x - 1, y):
            wall_corners.append(0)  # top-left
        if not _is_floor(level, x, y - 1) and \
                not _is_floor(level, x + 1, y):
            wall_corners.append(1)  # top-right
        if not _is_floor(level, x, y + 1) and \
                not _is_floor(level, x - 1, y):
            wall_corners.append(2)  # bottom-left
        if not _is_floor(level, x, y + 1) and \
                not _is_floor(level, x + 1, y):
            wall_corners.append(3)  # bottom-right
        if wall_corners:
            corner = rng.choice(wall_corners)
            webs.append(_web_detail(rng, px, py, corner))

    # Bone piles
    if rng.random() < probs.get("bones", 0):
        bones.append(_bone_detail(rng, px, py))

    # Skulls
    if rng.random() < probs.get("skull", 0):
        skulls.append(_skull_detail(rng, px, py))


def _emit_thematic_detail(
    svg: list[str],
    webs: list[str], bones: list[str], skulls: list[str],
) -> None:
    """Append thematic detail elements to the SVG."""
    if webs:
        svg.append(
            f'<g class="detail-webs">{"".join(webs)}</g>')
    if bones:
        svg.append(
            f'<g class="detail-bones">{"".join(bones)}</g>')
    if skulls:
        svg.append(
            f'<g class="detail-skulls">{"".join(skulls)}</g>')


def _dungeon_interior_clip(svg: list[str], dungeon_poly, clip_id: str):
    """Emit an SVG clipPath for the dungeon interior polygon.

    Includes interior holes (cave islands) so that grid lines
    and floor details are clipped away inside them, letting the
    hatching layer show through.
    """
    if dungeon_poly is None or dungeon_poly.is_empty:
        return
    geoms = (dungeon_poly.geoms
             if hasattr(dungeon_poly, 'geoms')
             else [dungeon_poly])
    clip_d = ""
    for geom in geoms:
        coords = list(geom.exterior.coords)
        clip_d += f'M{coords[0][0]:.0f},{coords[0][1]:.0f} '
        clip_d += ' '.join(
            f'L{x:.0f},{y:.0f}' for x, y in coords[1:])
        clip_d += ' Z '
        # Add interior holes so the clip excludes them
        for hole in geom.interiors:
            h = list(hole.coords)
            clip_d += f'M{h[0][0]:.0f},{h[0][1]:.0f} '
            clip_d += ' '.join(
                f'L{x:.0f},{y:.0f}' for x, y in h[1:])
            clip_d += ' Z '
    svg.append(
        f'<defs><clipPath id="{clip_id}">'
        f'<path d="{clip_d}" fill-rule="evenodd"/>'
        f'</clipPath></defs>')


_TERRAIN_TYPES = {Terrain.WATER, Terrain.GRASS, Terrain.LAVA, Terrain.CHASM}


def _render_terrain_tints(
    svg: list[str], level: "Level", dungeon_poly=None,
) -> None:
    """Render soft terrain tints and room-type hint washes.

    Emits semi-transparent colored rects for WATER, GRASS, LAVA,
    and CHASM tiles, plus very subtle room-type washes.  Clipped
    to the dungeon polygon so tints don't bleed outside rooms.
    """
    theme = level.metadata.theme if level.metadata else "dungeon"
    palette = get_palette(theme)

    terrain_map = {
        Terrain.WATER: palette.water,
        Terrain.GRASS: palette.grass,
        Terrain.LAVA: palette.lava,
        Terrain.CHASM: palette.chasm,
    }

    # ── Per-tile terrain tints ──
    tint_rects: list[str] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            style = terrain_map.get(tile.terrain)
            if style is None:
                continue
            tint_rects.append(
                f'<rect x="{x * CELL}" y="{y * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{style.tint}" opacity="{style.tint_opacity}"/>'
            )

    if tint_rects:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "terrain-clip")
            svg.append('<g clip-path="url(#terrain-clip)">')
            svg.extend(tint_rects)
            svg.append('</g>')
        else:
            svg.extend(tint_rects)

    # ── Room-type hint washes ──
    for room in level.rooms:
        tint_info = None
        for tag in room.tags:
            if tag in ROOM_TYPE_TINTS:
                tint_info = ROOM_TYPE_TINTS[tag]
                break
        if tint_info is None:
            continue
        color, opacity = tint_info
        r = room.rect
        svg.append(
            f'<rect x="{r.x * CELL}" y="{r.y * CELL}" '
            f'width="{r.width * CELL}" height="{r.height * CELL}" '
            f'fill="{color}" opacity="{opacity}"/>'
        )


def _render_floor_grid(
    svg: list[str], level: "Level", dungeon_poly=None,
) -> None:
    """Draw a hand-drawn style grid.

    Room tiles: generated for all tiles, clipped to dungeon polygon.
    Corridor/door tiles: generated directly, no clipping needed.
    """
    rng = random.Random(41)
    room_segments: list[str] = []
    corridor_segments: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            # Secret doors sit on the wall line between rooms
            # and fall outside the room shapely polygons used
            # by grid-clip. Route their grid edges through the
            # unclipped bucket alongside visible doors, so the
            # segment stroke doesn't land on the clip boundary
            # and get half-masked to invisibility.
            is_cor = (tile.is_corridor
                      or _is_door(level, x, y)
                      or tile.feature == "door_secret")
            px, py = x * CELL, y * CELL

            # Right edge
            if x + 1 < level.width:
                seg = _wobbly_grid_seg(
                    rng, px + CELL, py, px + CELL, py + CELL,
                    x * 0.7, y * 0.7, base=20,
                )
                if is_cor:
                    corridor_segments.append(seg)
                else:
                    room_segments.append(seg)

            # Bottom edge
            if y + 1 < level.height:
                seg = _wobbly_grid_seg(
                    rng, px, py + CELL, px + CELL, py + CELL,
                    x * 0.3, y * 0.7, base=24,
                )
                if is_cor:
                    corridor_segments.append(seg)
                else:
                    room_segments.append(seg)

    _GRID_STYLE = (
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{GRID_WIDTH}" '
        f'opacity="0.7" stroke-linecap="round"'
    )

    # Room grid — clipped to dungeon polygon
    if room_segments:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "grid-clip")
            svg.append(
                f'<path d="{" ".join(room_segments)}" '
                f'{_GRID_STYLE} clip-path="url(#grid-clip)"/>'
            )
        else:
            svg.append(
                f'<path d="{" ".join(room_segments)}" '
                f'{_GRID_STYLE}/>'
            )

    # Corridor grid — no clipping
    if corridor_segments:
        svg.append(
            f'<path d="{" ".join(corridor_segments)}" '
            f'{_GRID_STYLE}/>'
        )


def _render_floor_detail(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None,
) -> None:
    """Scatter cracks, stones, scratches, and thematic details.

    Room tiles: generated for all tiles, clipped to dungeon polygon.
    Corridor/door tiles: generated directly, no clipping needed.
    Thematic details (webs, bones, skulls) added based on theme.
    """
    rng = random.Random(seed + 99)
    theme = level.metadata.theme if level.metadata else "dungeon"
    scale = _DETAIL_SCALE.get(theme, 1.0)
    probs = _THEMATIC_DETAIL_PROBS.get(theme, _THEMATIC_DEFAULT)
    room_cracks: list[str] = []
    room_stones: list[str] = []
    room_scratches: list[str] = []
    cor_cracks: list[str] = []
    cor_stones: list[str] = []
    cor_scratches: list[str] = []
    room_webs: list[str] = []
    room_bones: list[str] = []
    room_skulls: list[str] = []
    cor_webs: list[str] = []
    cor_bones: list[str] = []
    cor_skulls: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            # Skip terrain tiles and stairs
            if tile.terrain in _TERRAIN_TYPES:
                continue
            if tile.feature in ("stairs_up", "stairs_down"):
                continue
            is_cor = (tile.is_corridor
                      or _is_door(level, x, y))
            if is_cor:
                _tile_detail(rng, x, y, seed,
                             cor_cracks, cor_stones, cor_scratches,
                             detail_scale=scale, theme=theme)
                _tile_thematic_detail(rng, x, y, level, probs,
                                     cor_webs, cor_bones, cor_skulls)
            else:
                _tile_detail(rng, x, y, seed,
                             room_cracks, room_stones, room_scratches,
                             detail_scale=scale, theme=theme)
                _tile_thematic_detail(rng, x, y, level, probs,
                                     room_webs, room_bones,
                                     room_skulls)

    # Room detail — clipped to dungeon polygon
    has_room = (room_cracks or room_stones or room_scratches
                or room_webs or room_bones or room_skulls)
    if has_room:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(svg, dungeon_poly, "detail-clip")
            svg.append('<g clip-path="url(#detail-clip)">')
            _emit_detail(svg, room_cracks, room_stones,
                         room_scratches)
            _emit_thematic_detail(svg, room_webs, room_bones,
                                 room_skulls)
            svg.append('</g>')
        else:
            _emit_detail(svg, room_cracks, room_stones,
                         room_scratches)
            _emit_thematic_detail(svg, room_webs, room_bones,
                                 room_skulls)

    # Corridor detail — no clipping
    has_cor = (cor_cracks or cor_stones or cor_scratches
               or cor_webs or cor_bones or cor_skulls)
    if has_cor:
        _emit_detail(svg, cor_cracks, cor_stones, cor_scratches)
        _emit_thematic_detail(svg, cor_webs, cor_bones, cor_skulls)


# ── Terrain detail ─────────────────────────────────────────────


def _water_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Wavy horizontal lines for a water tile."""
    elements: list[str] = []
    n_waves = rng.randint(2, 3)
    for i in range(n_waves):
        t = (i + 1) / (n_waves + 1)
        y0 = py + CELL * t
        # Build a wavy path across the tile
        segs = [f"M{px + CELL * 0.1:.1f},{y0:.1f}"]
        steps = 5
        for s in range(1, steps + 1):
            sx = px + CELL * 0.1 + (CELL * 0.8) * s / steps
            sy = y0 + rng.uniform(-CELL * 0.06, CELL * 0.06)
            segs.append(f"L{sx:.1f},{sy:.1f}")
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<path d="{" ".join(segs)}" fill="none" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 10% chance of a ripple circle
    if rng.random() < 0.10:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.06, CELL * 0.12)
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="none" stroke="{ink}" stroke-width="0.4"/>'
        )
    return elements


def _grass_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Short upward strokes for a grass tile."""
    elements: list[str] = []
    n_blades = rng.randint(3, 6)
    for _ in range(n_blades):
        bx = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        by = py + rng.uniform(CELL * 0.4, CELL * 0.9)
        h = rng.uniform(CELL * 0.12, CELL * 0.25)
        angle = rng.uniform(-0.3, 0.3)  # slight lean
        tx = bx + h * angle
        ty = by - h
        sw = rng.uniform(0.4, 0.8)
        elements.append(
            f'<line x1="{bx:.1f}" y1="{by:.1f}" '
            f'x2="{tx:.1f}" y2="{ty:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 15% chance of a converging tuft
    if rng.random() < 0.15:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.5, CELL * 0.8)
        for _ in range(3):
            dx = rng.uniform(-CELL * 0.08, CELL * 0.08)
            h = rng.uniform(CELL * 0.15, CELL * 0.25)
            elements.append(
                f'<line x1="{cx + dx:.1f}" y1="{cy:.1f}" '
                f'x2="{cx + dx * 0.3:.1f}" y2="{cy - h:.1f}" '
                f'stroke="{ink}" stroke-width="0.6" '
                f'stroke-linecap="round"/>'
            )
    return elements


def _lava_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Crack lines and ember dots for a lava tile."""
    elements: list[str] = []
    n_cracks = rng.randint(1, 2)
    for _ in range(n_cracks):
        x0 = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        y0 = py + rng.uniform(CELL * 0.1, CELL * 0.9)
        x1 = px + rng.uniform(CELL * 0.1, CELL * 0.9)
        y1 = py + rng.uniform(CELL * 0.1, CELL * 0.9)
        sw = rng.uniform(0.5, 1.0)
        elements.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
            f'x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    # 20% chance of ember circle
    if rng.random() < 0.20:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        r = rng.uniform(CELL * 0.04, CELL * 0.08)
        elements.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" '
            f'fill="{ink}" opacity="0.4"/>'
        )
    return elements


def _chasm_detail(
    rng: random.Random, px: float, py: float,
    ink: str, opacity: float,
) -> list[str]:
    """Diagonal hatch lines for a chasm tile."""
    elements: list[str] = []
    n_lines = rng.randint(2, 3)
    for i in range(n_lines):
        t = (i + 1) / (n_lines + 1)
        offset = CELL * t
        sw = rng.uniform(0.4, 0.8)
        # Diagonal from top-left to bottom-right direction
        x0 = px + offset + rng.uniform(-2, 2)
        y0 = py + rng.uniform(0, CELL * 0.15)
        x1 = px + offset + rng.uniform(-2, 2)
        y1 = py + CELL - rng.uniform(0, CELL * 0.15)
        elements.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
            f'x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="{ink}" stroke-width="{sw:.1f}" '
            f'stroke-linecap="round"/>'
        )
    return elements


_TERRAIN_DETAIL_FN = {
    Terrain.WATER: _water_detail,
    Terrain.GRASS: _grass_detail,
    Terrain.LAVA: _lava_detail,
    Terrain.CHASM: _chasm_detail,
}

_TERRAIN_CLASS = {
    Terrain.WATER: "terrain-water",
    Terrain.GRASS: "terrain-grass",
    Terrain.LAVA: "terrain-lava",
    Terrain.CHASM: "terrain-chasm",
}


def _render_terrain_detail(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None,
) -> None:
    """Render terrain-specific hand-drawn marks (wavy lines, etc.).

    Groups output by terrain type with CSS class markers for
    future canvas-layer targeting.
    """
    theme = level.metadata.theme if level.metadata else "dungeon"
    palette = get_palette(theme)
    terrain_styles = {
        Terrain.WATER: palette.water,
        Terrain.GRASS: palette.grass,
        Terrain.LAVA: palette.lava,
        Terrain.CHASM: palette.chasm,
    }

    rng = random.Random(seed + 200)

    # Collect elements per terrain type, split room vs corridor
    room_els: dict[Terrain, list[str]] = {t: [] for t in _TERRAIN_TYPES}
    cor_els: dict[Terrain, list[str]] = {t: [] for t in _TERRAIN_TYPES}

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            fn = _TERRAIN_DETAIL_FN.get(tile.terrain)
            if fn is None:
                continue
            style = terrain_styles[tile.terrain]
            px, py = x * CELL, y * CELL
            els = fn(rng, px, py, style.detail_ink, style.detail_opacity)
            if tile.is_corridor:
                cor_els[tile.terrain].extend(els)
            else:
                room_els[tile.terrain].extend(els)

    # Emit room terrain detail — clipped to dungeon polygon
    has_room = any(room_els[t] for t in _TERRAIN_TYPES)
    if has_room:
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            _dungeon_interior_clip(
                svg, dungeon_poly, "terrain-detail-clip",
            )
            svg.append(
                '<g clip-path="url(#terrain-detail-clip)">')
        for terrain_type in _TERRAIN_TYPES:
            els = room_els[terrain_type]
            if els:
                cls = _TERRAIN_CLASS[terrain_type]
                style = terrain_styles[terrain_type]
                svg.append(
                    f'<g class="{cls}" '
                    f'opacity="{style.detail_opacity}">'
                )
                svg.extend(els)
                svg.append('</g>')
        if dungeon_poly is not None and not dungeon_poly.is_empty:
            svg.append('</g>')

    # Emit corridor terrain detail — no clipping
    for terrain_type in _TERRAIN_TYPES:
        els = cor_els[terrain_type]
        if els:
            cls = _TERRAIN_CLASS[terrain_type]
            style = terrain_styles[terrain_type]
            svg.append(
                f'<g class="{cls}" '
                f'opacity="{style.detail_opacity}">'
            )
            svg.extend(els)
            svg.append('</g>')


def _wobble_line(
    rng: random.Random, x0: float, y0: float,
    x1: float, y1: float, seed: int, n_seg: int = 4,
) -> str:
    """Build a wobbly SVG path segment from (x0,y0) to (x1,y1).

    Uses Perlin noise to displace intermediate points perpendicular
    to the line direction, giving an organic hand-scratched look.
    """
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 0.1:
        return f"M{x0:.1f},{y0:.1f} L{x1:.1f},{y1:.1f}"
    # Unit perpendicular
    nx, ny = -dy / length, dx / length
    wobble = length * 0.12
    parts = [f"M{x0:.1f},{y0:.1f}"]
    for i in range(1, n_seg + 1):
        t = i / n_seg
        mx = x0 + dx * t
        my = y0 + dy * t
        if i < n_seg:  # don't wobble the endpoint
            w = _noise.pnoise2(
                mx * 0.15 + seed, my * 0.15, base=77) * wobble
            w += rng.uniform(-wobble * 0.3, wobble * 0.3)
            mx += nx * w
            my += ny * w
        parts.append(f"L{mx:.1f},{my:.1f}")
    return " ".join(parts)


def _edge_point(
    rng: random.Random, edge: int, px: float, py: float,
) -> tuple[float, float]:
    """Random point on a tile edge. Edges: 0=top, 1=right, 2=bottom, 3=left."""
    t = rng.uniform(0.15, 0.85)
    if edge == 0:
        return (px + t * CELL, py)
    if edge == 1:
        return (px + CELL, py + t * CELL)
    if edge == 2:
        return (px + t * CELL, py + CELL)
    return (px, py + t * CELL)


def _y_scratch(
    rng: random.Random, px: float, py: float,
    gx: int, gy: int, seed: int,
) -> str:
    """Y-shaped scratch with all 3 ends on tile edges.

    Picks 3 points on different tile edges, a fork point inside the
    tile, and draws 3 wobbly lines from the fork to each edge point.
    """
    # Pick 3 distinct edges
    edges = rng.sample([0, 1, 2, 3], 3)
    p0 = _edge_point(rng, edges[0], px, py)
    p1 = _edge_point(rng, edges[1], px, py)
    p2 = _edge_point(rng, edges[2], px, py)

    # Fork point: weighted average biased toward tile center
    # with some random jitter
    cx = (p0[0] + p1[0] + p2[0]) / 3
    cy = (p0[1] + p1[1] + p2[1]) / 3
    # Pull toward tile center and add jitter
    tc_x = px + CELL * 0.5
    tc_y = py + CELL * 0.5
    fx = cx * 0.4 + tc_x * 0.6 + rng.uniform(-CELL * 0.1, CELL * 0.1)
    fy = cy * 0.4 + tc_y * 0.6 + rng.uniform(-CELL * 0.1, CELL * 0.1)

    # Build 3 wobbly branches from fork to each edge point
    ns = seed + gx * 7 + gy
    b0 = _wobble_line(rng, fx, fy, p0[0], p0[1], ns, 4)
    b1 = _wobble_line(rng, fx, fy, p1[0], p1[1], ns + 13, 4)
    b2 = _wobble_line(rng, fx, fy, p2[0], p2[1], ns + 29, 4)

    sw = rng.uniform(0.3, 0.7)
    return (
        f'<path d="{b0} {b1} {b2}" '
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{sw:.1f}" '
        f'stroke-linecap="round"/>')


def _floor_stone(
    rng: random.Random, px: float, py: float,
    scale: float = 1.0,
) -> str:
    """Single floor stone ellipse — brown fill, scaled by *scale*."""
    sx = px + rng.uniform(CELL * 0.25, CELL * 0.75)
    sy = py + rng.uniform(CELL * 0.25, CELL * 0.75)
    rx = rng.uniform(2, CELL * 0.15) * scale
    ry = rng.uniform(2, CELL * 0.12) * scale
    angle = rng.uniform(0, 180)
    sw = rng.uniform(1.2, 2.0)
    return (
        f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
        f'fill="{FLOOR_STONE_FILL}" '
        f'stroke="{FLOOR_STONE_STROKE}" '
        f'stroke-width="{sw:.1f}"/>')


# ── Thematic detail generators ────────────────────────────────


def _web_detail(
    rng: random.Random, px: float, py: float,
    corner: int,
) -> str:
    """Spider web radiating from a tile corner.

    Draws 3-4 radial threads from the corner into the tile,
    connected by 2 concentric arc-like cross-threads.
    *corner*: 0=TL, 1=TR, 2=BL, 3=BR.
    """
    # Corner anchor point
    cx = px if corner in (0, 2) else px + CELL
    cy = py if corner in (0, 1) else py + CELL
    # Direction signs (into the tile)
    sx = 1 if corner in (0, 2) else -1
    sy = 1 if corner in (0, 1) else -1

    n_radials = rng.randint(3, 4)
    radial_len = rng.uniform(CELL * 0.5, CELL * 0.85)
    angles = sorted(
        rng.uniform(0, math.pi / 2) for _ in range(n_radials)
    )
    parts: list[str] = []

    # Radial endpoints at full length
    endpoints: list[list[tuple[float, float]]] = []
    for a in angles:
        dx = sx * math.cos(a) * radial_len
        dy = sy * math.sin(a) * radial_len
        ex, ey = cx + dx, cy + dy
        parts.append(
            f'M{cx:.1f},{cy:.1f} L{ex:.1f},{ey:.1f}'
        )
        # Store intermediate points for cross-threads
        ring_pts: list[tuple[float, float]] = []
        for frac in (0.4, 0.7):
            ring_pts.append((cx + dx * frac, cy + dy * frac))
        endpoints.append(ring_pts)

    # Cross-threads connecting radials at each ring
    for ring_idx in range(2):
        for i in range(len(endpoints) - 1):
            p1 = endpoints[i][ring_idx]
            p2 = endpoints[i + 1][ring_idx]
            # Slight sag for organic feel
            mx = (p1[0] + p2[0]) / 2 + rng.uniform(-1.5, 1.5)
            my = (p1[1] + p2[1]) / 2 + rng.uniform(-1.5, 1.5)
            parts.append(
                f'M{p1[0]:.1f},{p1[1]:.1f} '
                f'Q{mx:.1f},{my:.1f} '
                f'{p2[0]:.1f},{p2[1]:.1f}'
            )

    sw = rng.uniform(0.3, 0.6)
    return (
        f'<path d="{" ".join(parts)}" fill="none" '
        f'stroke="{INK}" stroke-width="{sw:.1f}" '
        f'stroke-linecap="round" opacity="0.35"/>'
    )


def _bone_detail(rng: random.Random, px: float, py: float) -> str:
    """Pile of 2-3 crossed bones with bulbous epiphyses.

    Each bone is a line with small circles at both ends,
    arranged in a small cluster within the tile.
    """
    cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
    cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
    n_bones = rng.randint(2, 3)
    parts: list[str] = []

    for _ in range(n_bones):
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(CELL * 0.2, CELL * 0.35)
        dx = math.cos(angle) * length / 2
        dy = math.sin(angle) * length / 2
        bx = cx + rng.uniform(-CELL * 0.08, CELL * 0.08)
        by = cy + rng.uniform(-CELL * 0.08, CELL * 0.08)
        x1, y1 = bx - dx, by - dy
        x2, y2 = bx + dx, by + dy
        # Bone shaft
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{INK}" stroke-width="1.2" '
            f'stroke-linecap="round"/>'
        )
        # Epiphyses (bulbous ends)
        er = rng.uniform(1.2, 1.8)
        for ex, ey in [(x1, y1), (x2, y2)]:
            parts.append(
                f'<ellipse cx="{ex:.1f}" cy="{ey:.1f}" '
                f'rx="{er:.1f}" ry="{er:.1f}" fill="{INK}"/>'
            )

    return f'<g opacity="0.4">{"".join(parts)}</g>'


def _skull_detail(rng: random.Random, px: float, py: float) -> str:
    """Small hand-drawn skull with separate cranium and mandible.

    Anatomy (top to bottom, all in local coords centered at 0,0):
    - Cranium: dome path curving from zygomatic arch, over the top,
      back down to the other arch.  Narrower at the bottom than a
      full ellipse so it reads as a skull, not a mask.
    - Eye sockets: two filled ellipses.
    - Nasal cavity: small inverted triangle.
    - Tooth line: short horizontal dashes between upper and lower jaw.
    - Mandible: separate U-shaped jawbone with ascending rami
      connecting near the zygomatic arches and a rounded chin.

    Fits within ~10-12px, positioned randomly inside the tile.
    """
    cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
    cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
    s = rng.uniform(0.8, 1.2)
    rot = rng.uniform(-20, 20)
    sw = 0.7  # stroke width

    # Proportions (half-widths/heights from center)
    cw = 4.5 * s   # cranium half-width at widest (temples)
    ch = 5.0 * s   # cranium half-height (top of dome to maxilla)
    zw = cw * 0.85  # zygomatic arch width (cheekbone, narrower)
    mw = cw * 0.55  # maxilla half-width (bottom of upper skull)

    parts: list[str] = []

    # ── Cranium path ──
    # Start at right zygomatic arch, arc over the dome, down to
    # left zygomatic, then straight across the maxilla base.
    top_y = -ch           # top of dome
    zyg_y = ch * 0.35     # zygomatic arch y (below center)
    max_y = ch * 0.55     # maxilla base y

    parts.append(
        f'<path d="'
        f'M{-zw:.1f},{zyg_y:.1f} '
        f'C{-cw:.1f},{-ch * 0.2:.1f} '    # left temple
        f'{-cw * 0.6:.1f},{top_y:.1f} '    # left-top
        f'0,{top_y:.1f} '                  # top center
        f'C{cw * 0.6:.1f},{top_y:.1f} '    # right-top
        f'{cw:.1f},{-ch * 0.2:.1f} '       # right temple
        f'{zw:.1f},{zyg_y:.1f} '           # right zygomatic
        f'L{mw:.1f},{max_y:.1f} '          # right maxilla
        f'L{-mw:.1f},{max_y:.1f} '         # left maxilla
        f'Z" '
        f'fill="none" stroke="{INK}" stroke-width="{sw}"/>'
    )

    # ── Eye sockets ──
    eye_y = -ch * 0.05
    eye_sep = cw * 0.42
    eye_rx = cw * 0.26
    eye_ry = ch * 0.16
    for ex in (-eye_sep, eye_sep):
        parts.append(
            f'<ellipse cx="{ex:.1f}" cy="{eye_y:.1f}" '
            f'rx="{eye_rx:.1f}" ry="{eye_ry:.1f}" '
            f'fill="{INK}"/>'
        )

    # ── Nasal cavity ──
    nose_y = ch * 0.2
    nose_w = cw * 0.18
    nose_h = ch * 0.2
    parts.append(
        f'<path d="M0,{nose_y:.1f} '
        f'L{-nose_w:.1f},{nose_y + nose_h:.1f} '
        f'L{nose_w:.1f},{nose_y + nose_h:.1f} Z" '
        f'fill="{INK}"/>'
    )

    # ── Tooth line ──
    tooth_y = max_y + s * 0.8
    tooth_w = mw * 0.75
    parts.append(
        f'<line x1="{-tooth_w:.1f}" y1="{tooth_y:.1f}" '
        f'x2="{tooth_w:.1f}" y2="{tooth_y:.1f}" '
        f'stroke="{INK}" stroke-width="0.4" '
        f'stroke-dasharray="1.2,0.8"/>'
    )

    # ── Mandible (jawbone) ──
    # U-shape: ascending rami from zygomatic arches curving down
    # to a rounded chin below the tooth line.
    jaw_top = max_y + s * 0.4   # top of ramus (near zygomatic)
    chin_y = max_y + ch * 0.55  # chin bottom
    ramus_w = mw * 1.05         # ramus outer width
    chin_w = mw * 0.35          # chin half-width at bottom

    parts.append(
        f'<path d="'
        f'M{-ramus_w:.1f},{jaw_top:.1f} '
        f'C{-ramus_w:.1f},{chin_y - s:.1f} '
        f'{-chin_w:.1f},{chin_y:.1f} '
        f'0,{chin_y:.1f} '
        f'C{chin_w:.1f},{chin_y:.1f} '
        f'{ramus_w:.1f},{chin_y - s:.1f} '
        f'{ramus_w:.1f},{jaw_top:.1f}" '
        f'fill="none" stroke="{INK}" stroke-width="{sw}"/>'
    )

    inner = "".join(parts)
    return (
        f'<g transform="translate({cx:.1f},{cy:.1f}) '
        f'rotate({rot:.0f})" opacity="0.45">{inner}</g>'
    )


def _render_walls_and_floors(
    svg: list[str], level: "Level",
    cave_wall_path: str | None = None,
    cave_wall_poly=None,
    cave_tiles: set[tuple[int, int]] | None = None,
) -> None:
    """Render walls and floor fills in one pass.

    Smooth rooms: outline drawn with fill=BG + stroke=INK,
    so the interior is filled and the wall is drawn together.
    Rect rooms: a filled BG rect, then tile-edge wall segments.
    Corridors: per-tile BG rects (no enclosing shape).

    The unified cave region (rooms + connected corridors) is
    rendered from the precomputed *cave_wall_path* and
    *cave_wall_poly* built by :func:`_build_cave_wall_geometry`.
    Both the floor fill and the wall stroke come from the same
    jittered polygon, so the wall silhouette and the floor fill
    are pixel-aligned — mirroring the strategy used for circular
    rooms where the circle polygon is both clip and fill.
    """


    _STROKE_STYLE = (
        f'stroke="{INK}" stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )

    # ── Unified cave region (rooms + connected corridors) ──
    # All tiles in this set skip the per-room cave branch, the
    # per-tile corridor rect fill, AND the per-tile straight-wall
    # segment loop below.  Rendering is driven by the precomputed
    # jittered polygon passed in from render_floor_svg.
    cave_region: set[tuple[int, int]] = cave_tiles or set()
    cave_region_rooms: set[int] = set()
    if cave_region:
        for idx, room in enumerate(level.rooms):
            if isinstance(room.shape, CaveShape):
                cave_region_rooms.add(idx)

    cave_region_svg: list[str] = []
    if cave_wall_path:
        # Use the same smoothed Bézier path for both fill and
        # stroke — the wall path already contains subpaths for
        # exterior + holes, so evenodd fill-rule cuts out holes
        # precisely along the same curves the stroke follows.
        cave_region_svg.append(cave_wall_path.replace(
            '/>',
            f' fill="{CAVE_FLOOR_COLOR}" stroke="none" '
            f'fill-rule="evenodd"/>',
        ))
        cave_region_svg.append(cave_wall_path.replace(
            '/>', f' fill="none" {_STROKE_STYLE}/>'))

    # ── Pre-compute smooth room outlines and wall data ──
    smooth_tiles: set[tuple[int, int]] = set()
    smooth_fills: list[str] = []
    smooth_walls: list[str] = []
    wall_extensions: list[str] = []
    for idx, room in enumerate(level.rooms):
        # Cave-region rooms are handled collectively above.
        if idx in cave_region_rooms:
            smooth_tiles |= room.floor_tiles()
            continue
        outline = _room_svg_outline(room)
        if not outline:
            continue
        openings = _find_doorless_openings(room, level)
        fill_el = outline.replace(
            '/>', f' fill="{FLOOR_COLOR}" stroke="none"/>')
        smooth_fills.append(fill_el)

        if openings:
            gapped, extensions = _outline_with_gaps(
                room, outline, openings,
            )
            wall_extensions.extend(extensions)
            smooth_walls.append(gapped.replace(
                '/>', f' fill="none" {_STROKE_STYLE}/>'))
            for _, _, cx, cy in openings:
                smooth_tiles.add((cx, cy))
        else:
            smooth_walls.append(outline.replace(
                '/>', f' fill="none" {_STROKE_STYLE}/>'))
        smooth_tiles |= room.floor_tiles()

    # Cave region tiles must also skip the per-tile wall segment
    # loop — their walls come from the organic outline above.
    smooth_tiles |= cave_region

    # ── 1. Corridors + doors: per-tile floor rects ──
    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in cave_region:
                continue
            tile = level.tiles[y][x]
            if tile.terrain not in (
                Terrain.FLOOR, Terrain.WATER,
                Terrain.GRASS, Terrain.LAVA,
            ):
                continue
            if tile.is_corridor or (tile.feature and "door" in
                                    (tile.feature or "")):
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" '
                    f'fill="{FLOOR_COLOR}" stroke="none"/>'
                )

    # ── 2. Rect rooms: filled rect ──
    for room in level.rooms:
        if isinstance(room.shape, RectShape):
            r = room.rect
            svg.append(
                f'<rect x="{r.x * CELL}" y="{r.y * CELL}" '
                f'width="{r.width * CELL}" height="{r.height * CELL}" '
                f'fill="{FLOOR_COLOR}" stroke="none"/>'
            )

    # ── 3. Smooth rooms: filled outline + wall stroke ──
    for el in smooth_fills:
        svg.append(el)
    # Cave region: unified floor fill + organic wall stroke.
    for el in cave_region_svg:
        svg.append(el)
    for el in smooth_walls:
        svg.append(el)
    if wall_extensions:
        svg.append(
            f'<path d="{" ".join(wall_extensions)}" '
            f'fill="none" {_STROKE_STYLE}/>'
        )

    # ── 4. Tile-edge wall segments (rect rooms + corridors) ──
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            if (x, y) in smooth_tiles:
                px, py = x * CELL, y * CELL
                for nx, ny, seg in [
                    (x, y - 1, f'M{px},{py} L{px + CELL},{py}'),
                    (x, y + 1,
                     f'M{px},{py + CELL} L{px + CELL},{py + CELL}'),
                    (x - 1, y, f'M{px},{py} L{px},{py + CELL}'),
                    (x + 1, y,
                     f'M{px + CELL},{py} L{px + CELL},{py + CELL}'),
                ]:
                    nb = level.tile_at(nx, ny)
                    if nb and nb.is_corridor and not _walkable(nx, ny):
                        segments.append(seg)
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


STAIR_FILL = "#E0E0E0"  # bright grey fill for stairs in caves


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
    theme = (level.metadata.theme
             if level.metadata else "dungeon")

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

            # In caves, fill the stair trapezoid with bright grey
            # so stairs stand out against the brown cave floor.
            if theme == "cave":
                left_x = px + m
                right_x = px + CELL - m
                if down:
                    pts = (f'{left_x:.1f},{cy - wide_h:.1f} '
                           f'{right_x:.1f},{cy - narrow_h:.1f} '
                           f'{right_x:.1f},{cy + narrow_h:.1f} '
                           f'{left_x:.1f},{cy + wide_h:.1f}')
                else:
                    pts = (f'{left_x:.1f},{cy - narrow_h:.1f} '
                           f'{right_x:.1f},{cy - wide_h:.1f} '
                           f'{right_x:.1f},{cy + wide_h:.1f} '
                           f'{left_x:.1f},{cy + narrow_h:.1f}')
                svg.append(
                    f'<polygon points="{pts}" '
                    f'fill="{STAIR_FILL}" stroke="none"/>')

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

def _render_hole_hatching(
    svg: list[str], level: "Level", seed: int,
    cave_wall_poly,
) -> None:
    """Render hatching inside interior holes of the cave polygon.

    Interior holes (islands of wall/void surrounded by floor) need
    hatching rendered AFTER the cave floor fill so it's not covered
    by the brown fill.  Uses the same grey underlay + stone style
    as the perimeter hatching.
    """
    rng = random.Random(seed + 777)
    polys = (
        list(cave_wall_poly.geoms)
        if hasattr(cave_wall_poly, 'geoms')
        else [cave_wall_poly]
    )
    hole_polys = []
    for p in polys:
        for interior in p.interiors:
            hole_polys.append(Polygon(interior.coords))
    if not hole_polys:
        return

    tile_fills: list[str] = []
    hatch_stones: list[str] = []
    hatch_lines: list[str] = []

    for gy in range(level.height):
        for gx in range(level.width):
            center = Point((gx + 0.5) * CELL, (gy + 0.5) * CELL)
            if not any(hp.contains(center) for hp in hole_polys):
                continue
            # Grey underlay
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')
            # Stones
            n_stones = rng.choices(
                [0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15],
            )[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
                hatch_stones.append(
                    f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
                    f'rx="{rx:.1f}" ry="{ry:.1f}" '
                    f'transform="rotate({angle:.0f},'
                    f'{sx:.1f},{sy:.1f})" '
                    f'fill="{HATCH_UNDERLAY}" '
                    f'stroke="{INK}" '
                    f'stroke-width="{sw:.1f}"/>')
            # Cross-hatch lines
            n_lines = rng.randint(2, 4)
            for _ in range(n_lines):
                x1 = (gx + rng.uniform(0.05, 0.95)) * CELL
                y1 = (gy + rng.uniform(0.05, 0.95)) * CELL
                angle = rng.uniform(0, math.pi)
                length = rng.uniform(CELL * 0.2, CELL * 0.5)
                x2 = x1 + math.cos(angle) * length
                y2 = y1 + math.sin(angle) * length
                sw = rng.uniform(0.8, 1.5)
                hatch_lines.append(
                    f'<line x1="{x1:.1f}" y1="{y1:.1f}" '
                    f'x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{INK}" stroke-width="{sw:.1f}" '
                    f'stroke-linecap="round"/>')

    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_stones:
        svg.append(
            f'<g opacity="0.5">{"".join(hatch_stones)}</g>')
    if hatch_lines:
        svg.append(
            f'<g opacity="0.5">{"".join(hatch_lines)}</g>')


def _render_hatching(
    svg: list[str], level: "Level", seed: int,
    dungeon_poly=None, hatch_distance: float = 2.0,
    cave_wall_poly=None,
) -> None:
    """Procedural cross-hatching around the dungeon perimeter.

    Uses Shapely for geometry clipping, Perlin noise for organic
    displacement, and tile-based section partitioning.

    *hatch_distance* is the max distance in tiles from the dungeon
    edge that hatching extends.  Interior holes in the cave wall
    polygon (islands of wall/void surrounded by floor) are also
    hatched.
    """
    rng = random.Random(seed)
    if dungeon_poly is None:
        dungeon_poly = _build_dungeon_polygon(level)
    if dungeon_poly.is_empty:
        return

    # No buffer — hatching renders right up to the dungeon edge.
    # Walls and floor fills (rendered after hatching) cover the
    # interior, so overlap is handled by the layer order.
    hatching_boundary = dungeon_poly

    # Collect interior holes from the cave wall polygon — these
    # are islands of wall/void surrounded by floor that should
    # receive hatching even though they're geometrically "inside"
    # the dungeon boundary.
    hole_polys: list = []
    if cave_wall_poly is not None and not cave_wall_poly.is_empty:
        polys = (
            list(cave_wall_poly.geoms)
            if hasattr(cave_wall_poly, 'geoms')
            else [cave_wall_poly]
        )
        for p in polys:
            for interior in p.interiors:
                hole_polys.append(Polygon(interior.coords))

    base_distance_limit = hatch_distance * CELL
    min_stroke = 1.0
    max_stroke = 1.8

    # Pre-compute floor tile set for grid-based skip check.
    # Using the tile grid instead of the polygon ensures every
    # floor tile is surrounded by hatching — the polygon boundary
    # can deviate from the tile grid due to jitter/smoothing,
    # leaving some adjacent wall tiles unhatched.  Any hatching
    # that overlaps floor area is covered by the floor fill.
    floor_set: set[tuple[int, int]] = set()
    for ty in range(level.height):
        for tx in range(level.width):
            if level.tiles[ty][tx].terrain == Terrain.FLOOR:
                floor_set.add((tx, ty))

    tile_fills: list[str] = []
    hatch_lines: list[str] = []
    hatch_stones: list[str] = []

    for gy in range(-1, level.height + 1):
        for gx in range(-1, level.width + 1):
            # Skip actual floor tiles — they're covered by fill
            if (gx, gy) in floor_set:
                continue
            # Distance: use nearest floor tile as reference
            # (faster than polygon boundary distance)
            min_dist = float('inf')
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    if (gx + dx, gy + dy) in floor_set:
                        min_dist = min(min_dist,
                                       math.hypot(dx, dy) * CELL)
            if min_dist == float('inf'):
                # No floor tile nearby — use polygon distance
                center = Point(
                    (gx + 0.5) * CELL, (gy + 0.5) * CELL)
                min_dist = hatching_boundary.boundary.distance(
                    center)
            dist = min_dist

            # Irregular contour: vary distance limit per tile with
            # Perlin noise so the hatching edge flows organically.
            # Caves use a fixed limit — dense, continuous hatching
            # sells the solid rock illusion.
            if cave_wall_poly is None:
                noise_var = _noise.pnoise2(
                    gx * 0.3, gy * 0.3, base=50) * CELL * 0.8
                tile_limit = base_distance_limit + noise_var
            else:
                tile_limit = base_distance_limit
            if dist > tile_limit:
                continue

            # Random discontinuities: skip ~10% of edge tiles.
            # Caves skip this — they need dense, continuous hatching
            # to sell the solid rock illusion.
            if (cave_wall_poly is None
                    and dist > base_distance_limit * 0.5
                    and rng.random() < 0.10):
                continue

            # Grey underlay tile
            tile_fills.append(
                f'<rect x="{gx * CELL}" y="{gy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{HATCH_UNDERLAY}"/>')

            # Scatter 0-2 stones of varying sizes in this tile
            n_stones = rng.choices([0, 1, 2, 3], weights=[0.25, 0.35, 0.25, 0.15])[0]
            for _ in range(n_stones):
                sx = (gx + rng.uniform(0.15, 0.85)) * CELL
                sy = (gy + rng.uniform(0.15, 0.85)) * CELL
                rx = rng.uniform(2, CELL * 0.25)
                ry = rng.uniform(2, CELL * 0.2)
                angle = rng.uniform(0, 180)
                sw = rng.uniform(1.2, 2.0)
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
            pts = _pick_section_points(corners, anchor, CELL, rng)
            sections = _build_sections(anchor, pts, corners)

            for i, section in enumerate(sections):
                if section.is_empty or section.area < 1:
                    continue
                if i == 0:
                    angle = math.atan2(
                        pts[1][1] - pts[0][1],
                        pts[1][0] - pts[0][0])
                else:
                    angle = rng.uniform(0, math.pi)

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
                    sw = rng.uniform(min_stroke, max_stroke)
                    hatch_lines.append(
                        f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" '
                        f'x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" '
                        f'stroke="{INK}" stroke-width="{sw:.2f}" '
                        f'stroke-linecap="round"/>')

    if not (tile_fills or hatch_lines or hatch_stones):
        return

    # Clip hatching to the exterior of the dungeon polygon.
    # Walls cover the tile-staircase-to-curve transition at
    # smooth room boundaries, so tile-based precision is fine.
    map_w = level.width * CELL
    map_h = level.height * CELL
    margin = CELL * 2
    clip_d = (
        f'M{-margin},{-margin} '
        f'H{map_w + margin} V{map_h + margin} '
        f'H{-margin} Z '
    )
    if not dungeon_poly.is_empty:
        geoms = (dungeon_poly.geoms
                 if hasattr(dungeon_poly, 'geoms')
                 else [dungeon_poly])
        for geom in geoms:
            coords = list(geom.exterior.coords)
            clip_d += f'M{coords[0][0]:.0f},{coords[0][1]:.0f} '
            clip_d += ' '.join(
                f'L{x:.0f},{y:.0f}' for x, y in coords[1:])
            clip_d += ' Z '
            # Do NOT add interior holes here — the evenodd rule
            # means the exterior ring already cuts out the dungeon
            # interior from the hatch region.  Interior holes
            # should remain INSIDE the hatch region (they are
            # void/wall islands that need hatching), so we leave
            # them out of the clip.  The outer rect + exterior
            # ring with evenodd = hatch everywhere EXCEPT dungeon
            # floor.  Adding holes would re-include dungeon floor
            # at the hole, but we actually want the opposite:
            # holes are NOT dungeon floor, so they should hatch.
            #
            # The trick: the exterior ring cuts out the dungeon.
            # Adding a hole ring (which is INSIDE the exterior)
            # would flip it back to "hatch" under evenodd — which
            # is exactly what we want.
            for hole in geom.interiors:
                h = list(hole.coords)
                clip_d += f'M{h[0][0]:.0f},{h[0][1]:.0f} '
                clip_d += ' '.join(
                    f'L{x:.0f},{y:.0f}' for x, y in h[1:])
                clip_d += ' Z '
    svg.append(
        f'<defs><clipPath id="hatch-clip">'
        f'<path d="{clip_d}" clip-rule="evenodd"/>'
        f'</clipPath></defs>')

    svg.append('<g clip-path="url(#hatch-clip)">')
    if tile_fills:
        svg.append(f'<g opacity="0.3">{"".join(tile_fills)}</g>')
    if hatch_lines:
        svg.append(f'<g opacity="0.5">{"".join(hatch_lines)}</g>')
    if hatch_stones:
        svg.append(f'<g>{"".join(hatch_stones)}</g>')
    svg.append('</g>')


def _room_shapely_polygon(room) -> Polygon | None:
    """Build a Shapely polygon from a room's smooth outline.

    Approximates circles and arcs with 64-segment polylines.
    Returns None for rect rooms (use tile rects instead).
    """

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
        # Truly degenerate (endpoints further than diameter)
        return [(ex, ey)]
    if d_sq < 1e-9:
        # Start == end
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
        # Clockwise in SVG (angles increase in screen coords)
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
    level: "Level",
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
        # Cave rooms in the unified region are covered collectively
        # by cave_wall_poly — skip their per-room outline.
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

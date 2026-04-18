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
from nhc.rendering._svg_helpers import (
    BG,
    CAVE_FLOOR_COLOR,
    CELL,
    FLOOR_COLOR,
    FLOOR_STONE_FILL,
    FLOOR_STONE_STROKE,
    GRID_WIDTH,
    HATCH_UNDERLAY,
    INK,
    PADDING,
    PILL_ARC_SEGMENTS,
    TEMPLE_ARC_SEGMENTS,
    WALL_THIN,
    WALL_WIDTH,
    _edge_point,
    _find_doorless_openings,
    _is_door,
    _is_floor,
    _wobble_line,
    _wobbly_grid_seg,
    _y_scratch,
)


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


from nhc.rendering._dungeon_polygon import (  # noqa: E402
    _approximate_arc,
    _build_dungeon_polygon,
    _build_sections,
    _get_edge_index,
    _pick_section_points,
    _room_shapely_polygon,
    _svg_path_to_polygon,
)
from nhc.rendering._shadows import (  # noqa: E402
    _render_corridor_shadows,
    _render_room_shadows,
    _room_shadow_svg,
)
from nhc.rendering._cave_geometry import (  # noqa: E402
    _build_cave_polygon,
    _build_cave_wall_geometry,
    _cave_region_walls,
    _cave_svg_outline,
    _centripetal_bezier_cps,
    _collect_cave_region,
    _densify_ring,
    _jitter_ring_outward,
    _ring_to_subpath,
    _smooth_closed_path,
    _smooth_open_path,
    _trace_cave_boundary_coords,
)


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


from nhc.rendering._stairs_svg import _render_stairs  # noqa: E402


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



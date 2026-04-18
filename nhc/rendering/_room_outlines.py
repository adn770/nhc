"""Room outline geometry — smooth outlines, gap handling, vertices.

Extracted from svg.py to reduce its size. All functions here deal with
computing room outlines for non-rectangular room shapes (circles,
octagons, pills, temples, crosses, hybrids) and inserting gaps where
corridors connect.
"""

from __future__ import annotations

import math

from nhc.dungeon.model import (
    CircleShape, CrossShape, HybridShape,
    OctagonShape, PillShape, Rect, RectShape, Room,
    TempleShape,
)
from nhc.dungeon.generators.cellular import CaveShape
from nhc.rendering._svg_helpers import (
    CELL,
    INK,
    PILL_ARC_SEGMENTS,
    TEMPLE_ARC_SEGMENTS,
    WALL_WIDTH,
)
from nhc.rendering._cave_geometry import _cave_svg_outline


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
    from nhc.rendering._dungeon_polygon import _svg_path_to_polygon

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

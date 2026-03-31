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
FLOOR_STONE_FILL = "#E8D5B8"  # soft brown for room floor stones
FLOOR_STONE_STROKE = "#666666"


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

    # Precompute tiles owned by smooth-outlined rooms so they
    # can be excluded from the tile-based grid/detail passes and
    # drawn separately with clipped smooth outlines.
    smooth_tiles: set[tuple[int, int]] = set()
    for room in level.rooms:
        if _room_svg_outline(room):
            smooth_tiles |= room.floor_tiles()

    # Layer 1: Room shadows (subtle)
    _render_room_shadows(svg, level)

    # Layer 2: Floor fills
    _render_floors(svg, level)

    # Layer 3: Soft floor grid (rooms + corridors, excluding smooth)
    _render_floor_grid(svg, level, smooth_tiles)

    # Layer 3b: Floor detail — cracks and stones (excluding smooth)
    _render_floor_detail(svg, level, seed, smooth_tiles)

    # Layer 4: Hatching (behind walls)
    _render_hatching(svg, level, seed)

    # Layer 4b: Fill smooth-shaped rooms over hatching
    _render_smooth_floor_fills(svg, level)

    # Layer 4c: Floor grid + detail inside smooth-shaped rooms
    _render_smooth_floor_grid(svg, level, seed)

    # Layer 4d: Re-draw grid lines at corridor↔smooth boundaries
    # (the smooth fill in 4b covers grid lines from layer 3 that
    # sit on the polygon edge or on corridor opening BG rects)
    filled_tiles = set(smooth_tiles)
    for room in level.rooms:
        if _room_svg_outline(room):
            for _, _, cx, cy in _find_doorless_openings(room, level):
                filled_tiles.add((cx, cy))
    _render_boundary_grid(svg, level, filled_tiles)

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


def _find_doorless_openings(
    room, level: "Level",
) -> list[tuple[int, int, int, int]]:
    """Find edges where corridors enter a room without a door.

    Returns list of (room_x, room_y, corridor_x, corridor_y).
    """
    from nhc.dungeon.model import Terrain
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
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HybridShape, OctagonShape,
    )
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
    elif isinstance(shape, (OctagonShape, CrossShape)):
        gapped = _polygon_with_gaps(shape, r, gaps)
    elif isinstance(shape, HybridShape):
        gapped = _hybrid_with_gaps(room, gaps)
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
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HybridShape, OctagonShape,
    )
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

    if isinstance(shape, (OctagonShape, CrossShape)):
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
    from nhc.dungeon.model import CircleShape, OctagonShape, RectShape
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
            from nhc.dungeon.model import Rect
            tw = r.width
            th = int(sub_ph / CELL)
            d = sub._diameter(Rect(0, 0, tw, th))
            radius = d * CELL / 2
            ccx = px + pw / 2
            ccy = sub_py + sub_ph / 2
        else:
            from nhc.dungeon.model import Rect
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
        from nhc.dungeon.model import Rect
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
    """Get pixel-space vertices for an octagon or cross shape."""
    from nhc.dungeon.model import CrossShape, OctagonShape
    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

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
    """Build an SVG path for a circle with gaps at openings."""
    r = rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL
    d = shape._diameter(r)
    radius = d * CELL / 2
    ccx = px + pw / 2
    ccy = py + ph / 2

    # Convert gap points to angles
    gap_angles = []
    for (ax, ay), (bx, by) in gaps:
        a1 = math.atan2(ay - ccy, ax - ccx)
        a2 = math.atan2(by - ccy, bx - ccx)
        # Ensure a1 < a2 going clockwise (SVG convention)
        if a1 > a2:
            a1, a2 = a2, a1
        gap_angles.append((a1, a2))

    # Sort by start angle
    gap_angles.sort()

    # Build arc segments between gaps
    # Walk from 0 to 2π, skipping gap intervals
    arcs = []
    # Collect all boundary angles
    boundaries = []
    for a1, a2 in gap_angles:
        boundaries.append(('end', a1))
        boundaries.append(('start', a2))

    if not boundaries:
        return None

    # Start from the end of the first gap, go around to the
    # start of the first gap
    parts = []
    # Normalize: walk clockwise from first gap end
    sorted_events = []
    for a1, a2 in gap_angles:
        sorted_events.append((a1, 'gap_start'))
        sorted_events.append((a2, 'gap_end'))
    sorted_events.sort()

    # Build segments: from each gap_end to next gap_start
    segments = []
    for i, (angle, event) in enumerate(sorted_events):
        if event == 'gap_end':
            # Find next gap_start
            next_idx = (i + 1) % len(sorted_events)
            next_angle, next_event = sorted_events[next_idx]
            if next_event == 'gap_start':
                segments.append((angle, next_angle))
            else:
                # Next is another gap_end, skip to its gap_start
                pass

    if not segments:
        # Single gap: draw from gap end all the way around to gap start
        a1, a2 = gap_angles[0]
        segments = [(a2, a1 + 2 * math.pi)]

    path_parts = []
    for start_a, end_a in segments:
        # Start point
        sx = ccx + radius * math.cos(start_a)
        sy = ccy + radius * math.sin(start_a)
        # End point
        ex = ccx + radius * math.cos(end_a)
        ey = ccy + radius * math.sin(end_a)
        # Arc sweep
        sweep_angle = end_a - start_a
        if sweep_angle < 0:
            sweep_angle += 2 * math.pi
        large = 1 if sweep_angle > math.pi else 0
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


def _hybrid_with_gaps(
    room, gaps: list[tuple],
) -> str | None:
    """Build an SVG path for a hybrid room with gaps in arcs.

    Reuses the original outline structure — side walls and rect
    edges stay intact, only the arc segment gets split at gap
    points.
    """
    from nhc.dungeon.model import (
        CircleShape, HybridShape, OctagonShape, Rect, RectShape,
    )
    shape = room.shape
    r = room.rect
    px, py = r.x * CELL, r.y * CELL
    pw, ph = r.width * CELL, r.height * CELL

    if shape.split == "horizontal":
        mid = py + (r.height // 2) * CELL
    else:
        mid = px + (r.width // 2) * CELL

    # Compute circle sub-shape geometry
    circle_sub = None
    circle_side = None
    for side_name, sub in [("left", shape.left), ("right", shape.right)]:
        if isinstance(sub, CircleShape):
            circle_sub = sub
            circle_side = side_name
            break

    if not circle_sub:
        return None  # no circle sub-shape to gap

    if shape.split == "horizontal":
        if circle_side == "left":
            sub_py, sub_ph = py, mid - py
        else:
            sub_py, sub_ph = mid, py + ph - mid
        tw, th = r.width, int(sub_ph / CELL)
        d = circle_sub._diameter(Rect(0, 0, tw, th))
        sub_r = d * CELL / 2
        ccx = px + pw / 2
        ccy = sub_py + sub_ph / 2
    else:
        if circle_side == "left":
            sub_px, sub_pw = px, mid - px
        else:
            sub_px, sub_pw = mid, px + pw - mid
        tw, th = int(sub_pw / CELL), r.height
        d = circle_sub._diameter(Rect(0, 0, tw, th))
        sub_r = d * CELL / 2
        ccx = sub_px + sub_pw / 2
        ccy = py + ph / 2

    # Determine the arc range for this semicircle.
    # The outline traces clockwise around the room.
    # For horizontal split:
    #   circle on top (left):  arc from left (π) → right (0), CW
    #   circle on bottom (right): arc from right (0) → left (π), CW
    # For vertical split:
    #   circle on left:  arc from top (-π/2) → bottom (π/2), CCW
    #   circle on right: arc from bottom (π/2) → top (-π/2), CCW
    if shape.split == "horizontal":
        if circle_side == "left":
            arc_start_a = math.pi
            arc_end_a = 0.0
            sweep_flag = 1
        else:
            arc_start_a = 0.0
            arc_end_a = math.pi
            sweep_flag = 1
    else:
        if circle_side == "left":
            arc_start_a = -math.pi / 2
            arc_end_a = math.pi / 2
            sweep_flag = 0
        else:
            arc_start_a = math.pi / 2
            arc_end_a = -math.pi / 2
            sweep_flag = 0

    def _arc_dist(angle: float) -> float:
        """Distance from arc_start to *angle* along the arc."""
        if sweep_flag == 1:
            d = angle - arc_start_a
        else:
            d = arc_start_a - angle
        return d % (2 * math.pi)

    # Classify each gap point: is it on the arc or on a line?
    # Points on the arc get converted to angles. Points on
    # transition diagonals are used as raw coordinates.
    # gap_entries: list of (break_angle_or_None, break_pt,
    #                        resume_angle_or_None, resume_pt)
    gap_entries = []
    for (ax, ay), (bx, by) in gaps:
        a1 = math.atan2(ay - ccy, ax - ccx)
        a2 = math.atan2(by - ccy, bx - ccx)
        # Check if each point is on the arc (distance from center ≈ r)
        d1 = math.sqrt((ax - ccx)**2 + (ay - ccy)**2)
        d2 = math.sqrt((bx - ccx)**2 + (by - ccy)**2)
        on_arc_1 = abs(d1 - sub_r) < 2.0
        on_arc_2 = abs(d2 - sub_r) < 2.0
        # Order by arc distance for on-arc points; for off-arc,
        # the one on the arc comes first (it's the break point)
        if on_arc_1 and on_arc_2:
            if _arc_dist(a1) > _arc_dist(a2):
                gap_entries.append((a2, (bx, by), a1, (ax, ay)))
            else:
                gap_entries.append((a1, (ax, ay), a2, (bx, by)))
        elif on_arc_1:
            # a1 is on arc (break), b is off-arc (resume)
            gap_entries.append((a1, (ax, ay), None, (bx, by)))
        elif on_arc_2:
            gap_entries.append((a2, (bx, by), None, (ax, ay)))
        else:
            # Both off-arc — shouldn't happen, skip
            continue
    gap_entries.sort(key=lambda g: _arc_dist(g[0]))

    arc_start_pt = (ccx + sub_r * math.cos(arc_start_a),
                    ccy + sub_r * math.sin(arc_start_a))
    arc_end_pt = (ccx + sub_r * math.cos(arc_end_a),
                  ccy + sub_r * math.sin(arc_end_a))

    # Build the arc portion with gaps
    def _arc_cmd(from_a: float, to_a: float) -> str:
        sx = ccx + sub_r * math.cos(from_a)
        sy = ccy + sub_r * math.sin(from_a)
        ex = ccx + sub_r * math.cos(to_a)
        ey = ccy + sub_r * math.sin(to_a)
        # Compute sweep angle (always going clockwise for sf=1)
        sweep = to_a - from_a
        if sweep_flag == 1:
            if sweep < 0:
                sweep += 2 * math.pi
        else:
            sweep = from_a - to_a
            if sweep < 0:
                sweep += 2 * math.pi
        large = 1 if sweep > math.pi else 0
        return (f'A{sub_r:.1f},{sub_r:.1f} 0 {large},'
                f'{sweep_flag} {ex:.1f},{ey:.1f}')

    # Build the complete outline path.  The hybrid outline
    # structure (horizontal split, circle on top) is:
    #   M left-mid → L left-arc-start → ARC → L right-mid
    #   → L right-bottom → L left-bottom → L left-mid Z
    # We keep the line segments and split only the arc.

    _ARC_TOL = 0.02  # ~1 degree tolerance for skip

    def _append_gapped_arc(parts: list[str], after_arc: str):
        """Append arc segments with gaps, then *after_arc* line."""
        cur_a = arc_start_a
        for break_a, break_pt, resume_a, resume_pt in gap_entries:
            # Arc from current pos to break point
            if _arc_dist(break_a) - _arc_dist(cur_a) > _ARC_TOL:
                parts[-1] += f' {_arc_cmd(cur_a, break_a)}'
            # Start new sub-path at resume point
            rx, ry = resume_pt
            if resume_a is not None:
                at_end = abs(
                    _arc_dist(resume_a) - _arc_dist(arc_end_a)
                ) < _ARC_TOL
            else:
                at_end = False
            if not at_end:
                parts.append(f'M{rx:.1f},{ry:.1f}')
            cur_a = resume_a if resume_a is not None else arc_end_a
        # Final arc from last resume to arc end
        remaining = _arc_dist(arc_end_a) - _arc_dist(cur_a)
        if remaining > _ARC_TOL:
            parts[-1] += f' {_arc_cmd(cur_a, arc_end_a)}'
        parts[-1] += after_arc

    parts = []

    if shape.split == "horizontal":
        if circle_side == "left":  # circle on top
            parts.append(
                f'M{px:.1f},{mid:.1f} '
                f'L{arc_start_pt[0]:.1f},{arc_start_pt[1]:.1f}')
            _append_gapped_arc(parts,
                f' L{px + pw:.1f},{mid:.1f}'
                f' L{px + pw:.1f},{py + ph:.1f}'
                f' L{px:.1f},{py + ph:.1f}'
                f' L{px:.1f},{mid:.1f}')
        else:  # circle on bottom
            parts.append(
                f'M{px + pw:.1f},{mid:.1f} '
                f'L{px + pw:.1f},{py:.1f} '
                f'L{px:.1f},{py:.1f} '
                f'L{px:.1f},{mid:.1f}'
                f' L{arc_start_pt[0]:.1f},{arc_start_pt[1]:.1f}')
            _append_gapped_arc(parts,
                f' L{px + pw:.1f},{mid:.1f}')
    else:
        if circle_side == "left":  # circle on left
            parts.append(
                f'M{mid:.1f},{py:.1f} '
                f'L{arc_start_pt[0]:.1f},{arc_start_pt[1]:.1f}')
            _append_gapped_arc(parts,
                f' L{mid:.1f},{py + ph:.1f}'
                f' L{px + pw:.1f},{py + ph:.1f}'
                f' L{px + pw:.1f},{py:.1f}'
                f' L{mid:.1f},{py:.1f}')
        else:  # circle on right
            parts.append(
                f'M{mid:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py + ph:.1f} '
                f'L{px:.1f},{py:.1f} '
                f'L{mid:.1f},{py:.1f}'
                f' L{arc_start_pt[0]:.1f},{arc_start_pt[1]:.1f}')
            _append_gapped_arc(parts,
                f' L{mid:.1f},{py + ph:.1f}')

    return f'<path d="{" ".join(parts)}"/>'


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
    from nhc.dungeon.model import (
        CircleShape, CrossShape, HybridShape,
        OctagonShape, RectShape,
    )
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

    # RectShape or unknown — use tile-edge walls
    return None


def _hybrid_svg_outline(room: "Room") -> str | None:
    """Build an SVG path for a hybrid room.

    Traces the outer contour combining the curved sub-shape on
    one side and straight lines on the rect side.
    """
    from nhc.dungeon.model import (
        CircleShape, HybridShape, OctagonShape, RectShape,
    )
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
    from nhc.dungeon.model import (
        CircleShape, OctagonShape, Rect, RectShape,
    )

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
        from nhc.dungeon.model import Rect
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


def _render_floors(svg: list[str], level: "Level") -> None:
    """Fill floor tiles with white."""
    for y in range(level.height):
        for x in range(level.width):
            if _is_floor(level, x, y) or _is_door(level, x, y):
                svg.append(
                    f'<rect x="{x * CELL}" y="{y * CELL}" '
                    f'width="{CELL}" height="{CELL}" fill="{BG}"/>'
                )


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


def _tile_detail(
    rng: random.Random, x: int, y: int, seed: int,
    cracks: list[str], stones: list[str], scratches: list[str],
) -> None:
    """Generate floor detail (cracks, stones, scratches) for one tile."""
    px, py = x * CELL, y * CELL

    roll = rng.random()
    if roll < 0.08:
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
    elif roll < 0.13:
        scratches.append(_y_scratch(rng, px, py, x, y, seed))

    if rng.random() < 0.06:
        stones.append(_floor_stone(rng, px, py))

    if rng.random() < 0.03:
        cx = px + rng.uniform(CELL * 0.3, CELL * 0.7)
        cy = py + rng.uniform(CELL * 0.3, CELL * 0.7)
        for _ in range(3):
            sx = cx + rng.uniform(-CELL * 0.2, CELL * 0.2)
            sy = cy + rng.uniform(-CELL * 0.2, CELL * 0.2)
            scale = rng.uniform(0.5, 1.3)
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


def _render_boundary_grid(
    svg: list[str], level: "Level",
    filled_tiles: set[tuple[int, int]],
) -> None:
    """Re-draw grid lines covered by smooth fills.

    The smooth floor fill (layer 4b) covers grid lines that sit
    on the polygon edge or on corridor opening BG rects.  This
    pass redraws grid edges where at least one side was filled
    over, excluding edges entirely inside smooth rooms (both
    sides in smooth interiors get their grid from the clipped
    smooth grid pass instead).
    """
    rng = random.Random(41)
    segments: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not (_is_floor(level, x, y) or _is_door(level, x, y)):
                continue
            a_filled = (x, y) in filled_tiles
            px, py_ = x * CELL, y * CELL

            # Right edge
            nx_floor = (_is_floor(level, x + 1, y)
                        or _is_door(level, x + 1, y))
            if nx_floor:
                b_filled = (x + 1, y) in filled_tiles
                if a_filled or b_filled:
                    segments.append(_wobbly_grid_seg(
                        rng, px + CELL, py_, px + CELL, py_ + CELL,
                        x * 0.7, y * 0.7, base=20,
                    ))

            # Bottom edge
            ny_floor = (_is_floor(level, x, y + 1)
                        or _is_door(level, x, y + 1))
            if ny_floor:
                b_filled = (x, y + 1) in filled_tiles
                if a_filled or b_filled:
                    segments.append(_wobbly_grid_seg(
                        rng, px, py_ + CELL, px + CELL, py_ + CELL,
                        x * 0.3, y * 0.7, base=24,
                    ))

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
            f'opacity="0.7" stroke-linecap="round"/>'
        )


def _render_floor_grid(
    svg: list[str], level: "Level",
    skip: set[tuple[int, int]] | None = None,
) -> None:
    """Draw a hand-drawn style grid on floor tiles.

    Tiles in *skip* are excluded (they get their grid from the
    smooth-shape renderer instead).
    """
    rng = random.Random(41)
    segments: list[str] = []
    _skip = skip or set()

    for y in range(level.height):
        for x in range(level.width):
            if (x, y) in _skip:
                continue
            if not (_is_floor(level, x, y) or _is_door(level, x, y)):
                continue
            px, py = x * CELL, y * CELL
            nx_floor = _is_floor(level, x + 1, y) or _is_door(level, x + 1, y)
            ny_floor = _is_floor(level, x, y + 1) or _is_door(level, x, y + 1)

            # Right edge — skip if BOTH tiles are in smooth rooms
            if nx_floor and not ((x, y) in _skip
                                 and (x + 1, y) in _skip):
                segments.append(_wobbly_grid_seg(
                    rng, px + CELL, py, px + CELL, py + CELL,
                    x * 0.7, y * 0.7, base=20,
                ))

            # Bottom edge
            if ny_floor and not ((x, y) in _skip
                                 and (x, y + 1) in _skip):
                segments.append(_wobbly_grid_seg(
                    rng, px, py + CELL, px + CELL, py + CELL,
                    x * 0.3, y * 0.7, base=24,
                ))

    if segments:
        svg.append(
            f'<path d="{" ".join(segments)}" fill="none" '
            f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
            f'opacity="0.7" stroke-linecap="round"/>'
        )


def _render_floor_detail(
    svg: list[str], level: "Level", seed: int,
    skip: set[tuple[int, int]] | None = None,
) -> None:
    """Scatter cracks and small stones on floor tiles.

    Tiles in *skip* are excluded (they get their detail from the
    smooth-shape renderer instead).
    """
    rng = random.Random(seed + 99)
    _skip = skip or set()
    cracks: list[str] = []
    stones: list[str] = []
    scratches: list[str] = []

    for y in range(level.height):
        for x in range(level.width):
            if not _is_floor(level, x, y):
                continue
            if (x, y) in _skip:
                # Consume RNG to keep deterministic sequence
                _tile_detail(rng, x, y, seed, [], [], [])
                continue
            _tile_detail(rng, x, y, seed, cracks, stones, scratches)

    _emit_detail(svg, cracks, stones, scratches)


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


def _floor_stone(rng: random.Random, px: float, py: float) -> str:
    """Single floor stone ellipse — original small size, brown fill."""
    sx = px + rng.uniform(CELL * 0.25, CELL * 0.75)
    sy = py + rng.uniform(CELL * 0.25, CELL * 0.75)
    rx = rng.uniform(2, CELL * 0.15)
    ry = rng.uniform(2, CELL * 0.12)
    angle = rng.uniform(0, 180)
    sw = rng.uniform(1.2, 2.0)
    return (
        f'<ellipse cx="{sx:.1f}" cy="{sy:.1f}" '
        f'rx="{rx:.1f}" ry="{ry:.1f}" '
        f'transform="rotate({angle:.0f},{sx:.1f},{sy:.1f})" '
        f'fill="{FLOOR_STONE_FILL}" '
        f'stroke="{FLOOR_STONE_STROKE}" '
        f'stroke-width="{sw:.1f}"/>')


def _render_smooth_floor_fills(svg: list[str], level: "Level") -> None:
    """Fill smooth-shaped rooms with BG color over the hatching layer.

    The hatching pass covers the full map area; this paints over it
    inside non-rect rooms so the floor is clean before walls are drawn.
    Also clears hatching on corridor tiles at doorless openings.
    """
    fills: list[str] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if not outline:
            continue
        # Replace the closing /> with fill attribute
        el = outline.replace(
            '/>',
            f' fill="{BG}" stroke="none"/>')
        fills.append(el)
        # Clear hatching on corridor tiles at doorless openings
        for opening in _find_doorless_openings(room, level):
            _, _, cx, cy = opening
            fills.append(
                f'<rect x="{cx * CELL}" y="{cy * CELL}" '
                f'width="{CELL}" height="{CELL}" '
                f'fill="{BG}" stroke="none"/>'
            )
    if fills:
        svg.append(f'<g>{"".join(fills)}</g>')


def _render_smooth_floor_grid(
    svg: list[str], level: "Level", seed: int = 0,
) -> None:
    """Draw floor grid and detail inside smooth-shaped rooms.

    Uses SVG clip paths to extend the wobbly grid and floor detail
    (cracks, stones, scratches) to the smooth shape boundary.
    Reuses the same helpers as the tile-based renderer.
    """
    rooms_with_outlines: list[tuple] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if outline:
            rooms_with_outlines.append((room, outline))

    if not rooms_with_outlines:
        return

    grid_rng = random.Random(41)
    detail_rng = random.Random(seed + 99)

    for idx, (room, outline) in enumerate(rooms_with_outlines):
        r = room.rect
        clip_id = f"smooth-clip-{idx}"

        clip_el = outline.replace('/>', ' fill="white"/>')
        svg.append(
            f'<defs><clipPath id="{clip_id}">'
            f'{clip_el}</clipPath></defs>')

        # Per-tile-edge grid segments spanning the bounding rect,
        # clipped to the shape. Same short segments as the tile-based
        # grid so wobble and gaps look identical.
        segments: list[str] = []
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                px, py = x * CELL, y * CELL
                # Right edge (vertical)
                if x + 1 < r.x2:
                    segments.append(_wobbly_grid_seg(
                        grid_rng,
                        px + CELL, py, px + CELL, py + CELL,
                        x * 0.7, y * 0.7, base=20,
                    ))
                # Bottom edge (horizontal)
                if y + 1 < r.y2:
                    segments.append(_wobbly_grid_seg(
                        grid_rng,
                        px, py + CELL, px + CELL, py + CELL,
                        x * 0.3, y * 0.7, base=24,
                    ))

        if segments:
            svg.append(
                f'<path d="{" ".join(segments)}" fill="none" '
                f'stroke="{INK}" stroke-width="{GRID_WIDTH}" '
                f'opacity="0.7" stroke-linecap="round" '
                f'clip-path="url(#{clip_id})"/>')

        # Floor detail (cracks, stones, scratches) clipped
        cracks: list[str] = []
        stones: list[str] = []
        scratches: list[str] = []
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                _tile_detail(
                    detail_rng, x, y, seed,
                    cracks, stones, scratches,
                )

        # Wrap detail in a clipped group
        detail_els: list[str] = []
        if cracks:
            crack_lines = "".join(
                f'<line x1="{c.split()[0].split(",")[0]}" '
                f'y1="{c.split()[0].split(",")[1]}" '
                f'x2="{c.split()[1].split(",")[0]}" '
                f'y2="{c.split()[1].split(",")[1]}" '
                f'stroke="{INK}" stroke-width="0.5" '
                f'stroke-linecap="round"/>'
                for c in cracks
            )
            detail_els.append(f'<g opacity="0.5">{crack_lines}</g>')
        if scratches:
            detail_els.append(
                f'<g opacity="0.45">{"".join(scratches)}</g>')
        if stones:
            detail_els.append(
                f'<g opacity="0.8">{"".join(stones)}</g>')
        if detail_els:
            svg.append(
                f'<g clip-path="url(#{clip_id})">'
                f'{"".join(detail_els)}</g>')



def _render_walls(svg: list[str], level: "Level") -> None:
    """Render walls around rooms and corridors.

    Rooms with smooth geometric shapes (circle, octagon) get
    proper SVG outlines (ellipse, polygon) with gaps where
    doorless corridors enter.  All other walls use tile-edge
    segments like terminal box-drawing.
    """
    # Collect floor tiles belonging to smooth-outlined rooms so
    # we can skip their tile-edge walls
    smooth_tiles: set[tuple[int, int]] = set()
    smooth_outlines: list[str] = []
    wall_extensions: list[str] = []
    for room in level.rooms:
        outline = _room_svg_outline(room)
        if not outline:
            continue
        openings = _find_doorless_openings(room, level)
        if openings:
            gapped, extensions = _outline_with_gaps(
                room, outline, openings,
            )
            smooth_outlines.append(gapped)
            wall_extensions.extend(extensions)
            # Add corridor tiles at openings to smooth_tiles so
            # the tile-edge renderer skips their walls (handled
            # by the wall extensions instead)
            for _, _, cx, cy in openings:
                smooth_tiles.add((cx, cy))
        else:
            smooth_outlines.append(outline)
        smooth_tiles |= room.floor_tiles()

    # Draw smooth room outlines (with gaps where corridors enter)
    _WALL_STYLE = (
        f'fill="none" stroke="{INK}" '
        f'stroke-width="{WALL_WIDTH}" '
        f'stroke-linecap="round" stroke-linejoin="round"'
    )
    if smooth_outlines:
        styled = []
        for el in smooth_outlines:
            el = el.replace('/>', f' {_WALL_STYLE}/>')
            styled.append(el)
        svg.append(f'<g>{"".join(styled)}</g>')
    if wall_extensions:
        svg.append(
            f'<path d="{" ".join(wall_extensions)}" '
            f'{_WALL_STYLE}/>'
        )

    # Tile-edge walls for corridors, doors, and rect rooms
    segments: list[str] = []

    def _walkable(x: int, y: int) -> bool:
        return _is_floor(level, x, y) or _is_door(level, x, y)

    for y in range(level.height):
        for x in range(level.width):
            if not _walkable(x, y):
                continue
            # Skip tiles that belong to a smooth-outlined room,
            # UNLESS the neighbor is a corridor or door (we still
            # need those connection edges)
            if (x, y) in smooth_tiles:
                # Only draw edges where this tile meets a corridor
                # or another room — skip edges facing void/wall
                # (those are covered by the smooth outline)
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

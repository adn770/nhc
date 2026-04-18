"""Shared predicates and geometry utilities for SVG rendering."""

from __future__ import annotations

import math
import random

import noise as _noise

from nhc.dungeon.model import Level, Terrain

# ── Constants (shared across SVG modules) ──────────────────────────

CELL = 32          # pixels per grid cell
PADDING = 32       # padding around the map (must match web client)
WALL_WIDTH = 5.0   # wall stroke width (bold Dyson style)
WALL_THIN = 2.0    # thinner wall for corridors
GRID_WIDTH = 0.3   # soft floor grid line width
PILL_ARC_SEGMENTS = 12
TEMPLE_ARC_SEGMENTS = 12
HATCH_UNDERLAY = "#D0D0D0"

BG = "#F5EDE0"
FLOOR_COLOR = "#FFFFFF"
CAVE_FLOOR_COLOR = "#F5EBD8"
INK = "#000000"
FLOOR_STONE_FILL = "#E8D5B8"
FLOOR_STONE_STROKE = "#666666"


def _is_floor(level: Level, x: int, y: int) -> bool:

    if not level.in_bounds(x, y):
        return False
    t = level.tiles[y][x]
    return t.terrain in (Terrain.FLOOR, Terrain.WATER, Terrain.GRASS)


def _is_door(level: Level, x: int, y: int) -> bool:
    """True for visible doors (not secret — those look like walls)."""
    if not level.in_bounds(x, y):
        return False
    f = level.tiles[y][x].feature
    return f in ("door_closed", "door_open", "door_locked")


def _find_doorless_openings(
    room, level: Level,
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

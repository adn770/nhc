"""Polygon construction for the web client's clearHatch pass.

Mirrors the algorithm in ``nhc/web/static/js/map.js`` so the
debug bundle can export the same geometry the JS client computes
at runtime. The two implementations must stay in sync; the unit
tests in ``tests/unit/test_hatch_polygon.py`` pin the expected
shape of the output so drift is caught before it ships.

The pipeline has two steps:

1. :func:`build_tile_set_polygons` traces directed perimeter
   edges around a set of walkable tiles, stitches them into
   closed loops, and collapses colinear runs sharing the same
   wall flag. Each edge carries the per-tile wall-mask bit for
   its direction so downstream code knows which edges to inflate.

2. :func:`offset_loop` pushes wall edges outward along their
   left-hand normal by a fixed pixel distance. Non-wall edges
   stay on the original tile boundary; vertices are recomputed
   as the intersection of consecutive offset lines, with a
   perpendicular bridge inserted at colinear wall↔non-wall
   transitions where the two offset lines are parallel.
"""

from __future__ import annotations

from dataclasses import dataclass

# Wall-mask bits. Must match _WALL_* in web_client.py and the
# WALL_N/E/S/W constants in map.js.
WALL_N = 1
WALL_E = 2
WALL_S = 4
WALL_W = 8


@dataclass
class Edge:
    """Directed polygon edge in pixel space."""

    ax: float
    ay: float
    bx: float
    by: float
    wall: bool

    def to_dict(self) -> dict:
        return {
            "ax": self.ax, "ay": self.ay,
            "bx": self.bx, "by": self.by,
            "wall": self.wall,
        }


def build_tile_set_polygons(
    walls: dict[tuple[int, int], int],
    cell_size: int,
    padding: int,
) -> list[list[Edge]]:
    """Trace closed perimeter loops around walkable tiles.

    ``walls`` maps ``(tx, ty)`` tile coordinates to a 4-bit wall
    mask (bit 0=N, 1=E, 2=S, 3=W). Returns a list of loops, each
    of which is a list of :class:`Edge` in clockwise order for
    outer boundaries (counter-clockwise for holes, to be filled
    with the non-zero rule). Handles multiple disjoint
    components naturally.
    """
    # "pixel corner" → list of (next_x, next_y, wall) outgoing.
    outgoing: dict[tuple[int, int], list[tuple[int, int, bool]]] = {}

    def push(ax: int, ay: int, bx: int, by: int, wall: bool) -> None:
        outgoing.setdefault((ax, ay), []).append((bx, by, wall))

    for (tx, ty), mask in walls.items():
        x0 = tx * cell_size + padding
        y0 = ty * cell_size + padding
        x1 = x0 + cell_size
        y1 = y0 + cell_size
        if (tx, ty - 1) not in walls:
            push(x0, y0, x1, y0, bool(mask & WALL_N))
        if (tx + 1, ty) not in walls:
            push(x1, y0, x1, y1, bool(mask & WALL_E))
        if (tx, ty + 1) not in walls:
            push(x1, y1, x0, y1, bool(mask & WALL_S))
        if (tx - 1, ty) not in walls:
            push(x0, y1, x0, y0, bool(mask & WALL_W))

    loops: list[list[Edge]] = []
    max_iters = len(walls) * 4 + 16
    safety = 0
    while outgoing and safety < max_iters:
        safety += 1
        # Pick any starting corner with outgoing edges.
        start = next(iter(outgoing))
        sx, sy = start
        raw: list[Edge] = []
        cx, cy = sx, sy
        guard = 0
        while guard < max_iters:
            guard += 1
            lst = outgoing.get((cx, cy))
            if not lst:
                break
            nxt_x, nxt_y, wall = lst.pop(0)
            if not lst:
                del outgoing[(cx, cy)]
            raw.append(Edge(
                ax=cx, ay=cy, bx=nxt_x, by=nxt_y, wall=wall,
            ))
            cx, cy = nxt_x, nxt_y
            if (cx, cy) == (sx, sy):
                break
        if len(raw) < 3:
            continue

        # Collapse runs of colinear edges that share the wall
        # flag. Adjacent 1-cell segments along a straight wall
        # become one edge, which is cheaper to offset and keeps
        # the bridge logic in ``offset_loop`` tight.
        merged: list[Edge] = []
        for e in raw:
            if merged:
                last = merged[-1]
                ldx = last.bx - last.ax
                ldy = last.by - last.ay
                edx = e.bx - e.ax
                edy = e.by - e.ay
                if (ldx * edy == ldy * edx
                        and last.wall == e.wall
                        and last.bx == e.ax
                        and last.by == e.ay):
                    last.bx = e.bx
                    last.by = e.by
                    continue
            merged.append(Edge(
                ax=e.ax, ay=e.ay, bx=e.bx, by=e.by, wall=e.wall,
            ))

        # The loop closes between merged[-1] and merged[0]; if
        # that seam is itself colinear with matching flag, fold
        # the first edge into the last.
        if len(merged) >= 2:
            first = merged[0]
            last = merged[-1]
            ldx = last.bx - last.ax
            ldy = last.by - last.ay
            fdx = first.bx - first.ax
            fdy = first.by - first.ay
            if (ldx * fdy == ldy * fdx
                    and last.wall == first.wall
                    and last.bx == first.ax
                    and last.by == first.ay):
                first.ax = last.ax
                first.ay = last.ay
                merged.pop()

        if len(merged) >= 3:
            loops.append(merged)
    return loops


def offset_loop(
    loop: list[Edge], dist: float,
) -> list[tuple[float, float]]:
    """Offset wall edges outward by ``dist`` pixels.

    Non-wall edges stay on their original line. Vertices are
    recomputed as the intersection of consecutive offset lines.
    When two adjacent offset lines are parallel (the colinear
    wall↔non-wall transition case), the function emits a
    perpendicular bridge — the end of the previous offset edge
    followed by the start of the current one — so the polygon
    steps cleanly between the two offset levels.
    """
    n = len(loop)
    if n < 3:
        return []

    lines: list[tuple[float, float, float, float]] = []
    for e in loop:
        dx = e.bx - e.ax
        dy = e.by - e.ay
        length = (dx * dx + dy * dy) ** 0.5
        if length == 0:
            continue
        d = dist if e.wall else 0.0
        # Left-hand (outward) normal in screen coords: (dy, -dx).
        nx = dy / length
        ny = -dx / length
        lines.append((
            e.ax + nx * d, e.ay + ny * d,
            e.bx + nx * d, e.by + ny * d,
        ))

    m = len(lines)
    if m < 3:
        return []

    out: list[tuple[float, float]] = []
    for i in range(m):
        p_ax, p_ay, p_bx, p_by = lines[(i - 1) % m]
        c_ax, c_ay, c_bx, c_by = lines[i]
        denom = ((p_ax - p_bx) * (c_ay - c_by)
                 - (p_ay - p_by) * (c_ax - c_bx))
        if abs(denom) < 1e-9:
            # Parallel offset lines — emit a perpendicular
            # bridge across the flag transition.
            out.append((p_bx, p_by))
            out.append((c_ax, c_ay))
            continue
        t = (((p_ax - c_ax) * (c_ay - c_by)
              - (p_ay - c_ay) * (c_ax - c_bx)) / denom)
        out.append((
            p_ax + t * (p_bx - p_ax),
            p_ay + t * (p_by - p_ay),
        ))
    return out

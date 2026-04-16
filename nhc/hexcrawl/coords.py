"""Axial coordinate math for flat-top hexes.

Convention (Red Blob Games "axial" for flat-top):

* The ``q`` axis steps SE between hex centres.
* The ``r`` axis steps S between hex centres.
* Six neighbours: N, NE, SE, S, SW, NW.

The neighbour offsets are exposed as :data:`NEIGHBOR_OFFSETS` so that
downstream code can iterate them in a stable order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HexCoord:
    """An axial hex coordinate ``(q, r)``."""

    q: int
    r: int


# Six neighbour offsets in stable order: N, NE, SE, S, SW, NW.
# Order is significant: ``ring()`` walks them anchored at index 4 (NW)
# so the resulting ring starts at the NW-most hex and proceeds CW.
NEIGHBOR_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, -1),    # N
    (1, -1),    # NE
    (1, 0),     # SE
    (0, 1),     # S
    (-1, 1),    # SW
    (-1, 0),    # NW
)


def neighbors(c: HexCoord) -> list[HexCoord]:
    """Return the six neighbour hexes of ``c`` in stable order."""
    return [HexCoord(c.q + dq, c.r + dr) for dq, dr in NEIGHBOR_OFFSETS]


def distance(a: HexCoord, b: HexCoord) -> int:
    """Hex distance between two axial coordinates.

    Uses the cube-distance identity in axial form:

        d = (|dq| + |dr| + |dq + dr|) / 2
    """
    dq = a.q - b.q
    dr = a.r - b.r
    return (abs(dq) + abs(dr) + abs(dq + dr)) // 2


def line(a: HexCoord, b: HexCoord) -> list[HexCoord]:
    """Return the inclusive line of hexes from ``a`` to ``b``.

    Implementation: lerp in cube space, round to nearest cube
    coordinate at each step, convert back to axial.
    """
    n = distance(a, b)
    if n == 0:
        return [a]
    return [_cube_round_to_axial(_cube_lerp(a, b, i / n)) for i in range(n + 1)]


def ring(center: HexCoord, radius: int) -> list[HexCoord]:
    """Return the ring of hexes at exactly ``radius`` from ``center``.

    Special-case ``radius == 0`` returns ``[center]``. For radius ``r``
    the ring contains ``6 * r`` hexes.

    Algorithm: anchor at ``center + radius * direction[0]`` (the N-most
    ring hex), then walk six sides clockwise. On each side the walk
    direction is ``(anchor_dir + 2) mod 6`` plus the side index, which
    traces an edge of the hex ring exactly ``radius`` steps long.
    """
    if radius < 0:
        raise ValueError(f"ring radius must be >= 0, got {radius}")
    if radius == 0:
        return [center]
    anchor_dir = 0          # N
    walk_start = 2          # N anchor walks in SE direction first
    aq, ar = NEIGHBOR_OFFSETS[anchor_dir]
    cur = HexCoord(center.q + aq * radius, center.r + ar * radius)
    out: list[HexCoord] = []
    for side in range(6):
        dq, dr = NEIGHBOR_OFFSETS[(walk_start + side) % 6]
        for _ in range(radius):
            out.append(cur)
            cur = HexCoord(cur.q + dq, cur.r + dr)
    return out


def to_pixel(c: HexCoord, size: float) -> tuple[float, float]:
    """Project an axial hex centre to pixel coordinates (flat-top).

    With ``size`` measured from hex centre to a corner:

        x = size * 3/2 * q
        y = size * (sqrt(3)/2 * q + sqrt(3) * r)
    """
    x = size * 1.5 * c.q
    y = size * (math.sqrt(3) / 2 * c.q + math.sqrt(3) * c.r)
    return (x, y)


def in_bounds(c: HexCoord, width: int, height: int) -> bool:
    """True iff ``0 <= q < width`` and ``0 <= r < height``."""
    return 0 <= c.q < width and 0 <= c.r < height


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _cube_lerp(a: HexCoord, b: HexCoord, t: float) -> tuple[float, float, float]:
    aq, ar = a.q, a.r
    bq, br = b.q, b.r
    a_s = -aq - ar
    b_s = -bq - br
    return (
        aq + (bq - aq) * t,
        ar + (br - ar) * t,
        a_s + (b_s - a_s) * t,
    )


def _cube_round_to_axial(cube: tuple[float, float, float]) -> HexCoord:
    fq, fr, fs = cube
    rq = round(fq)
    rr = round(fr)
    rs = round(fs)
    dq = abs(rq - fq)
    dr = abs(rr - fr)
    ds = abs(rs - fs)
    if dq > dr and dq > ds:
        rq = -rr - rs
    elif dr > ds:
        rr = -rq - rs
    return HexCoord(rq, rr)

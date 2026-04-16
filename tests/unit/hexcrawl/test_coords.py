"""Axial coordinate math for flat-top hexes.

Conventions (Red Blob Games "axial" for flat-top):

* ``q`` axis steps SE between hex centres
* ``r`` axis steps S between hex centres
* Six neighbours: N, NE, SE, S, SW, NW
"""

from __future__ import annotations

import math
import random

from nhc.hexcrawl.coords import (
    HexCoord,
    NEIGHBOR_OFFSETS,
    distance,
    in_bounds,
    line,
    neighbors,
    ring,
    to_pixel,
)


# ---------------------------------------------------------------------------
# HexCoord
# ---------------------------------------------------------------------------


def test_hexcoord_equality_and_hash() -> None:
    a = HexCoord(2, 3)
    b = HexCoord(2, 3)
    c = HexCoord(3, 2)
    assert a == b
    assert hash(a) == hash(b)
    assert a != c
    # frozen / hashable: usable in sets and dict keys
    assert {a, b, c} == {a, c}
    assert {a: 1}[b] == 1


# ---------------------------------------------------------------------------
# Neighbours
# ---------------------------------------------------------------------------


def test_neighbors_returns_six_distinct() -> None:
    n = neighbors(HexCoord(0, 0))
    assert len(n) == 6
    assert len(set(n)) == 6


def test_neighbors_offsets_match_flat_top_axial() -> None:
    # Expected six neighbour offsets for flat-top axial (q steps SE,
    # r steps S). Order is N, NE, SE, S, SW, NW.
    expected = {
        HexCoord(0, -1),   # N
        HexCoord(1, -1),   # NE
        HexCoord(1, 0),    # SE
        HexCoord(0, 1),    # S
        HexCoord(-1, 1),   # SW
        HexCoord(-1, 0),   # NW
    }
    assert set(neighbors(HexCoord(0, 0))) == expected
    # Same offsets exposed as a constant for downstream code.
    assert {HexCoord(*o) for o in NEIGHBOR_OFFSETS} == expected


def test_neighbors_translate_with_origin() -> None:
    base = HexCoord(5, -2)
    n = neighbors(base)
    expected = {HexCoord(5 + dq, -2 + dr) for dq, dr in NEIGHBOR_OFFSETS}
    assert set(n) == expected


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------


def test_distance_zero_for_self() -> None:
    c = HexCoord(4, 7)
    assert distance(c, c) == 0


def test_distance_one_for_neighbors() -> None:
    origin = HexCoord(0, 0)
    for n in neighbors(origin):
        assert distance(origin, n) == 1


def test_distance_axial_three_random_cases() -> None:
    # Hand-checked against the cube-distance formula:
    # d = (|dq| + |dr| + |dq + dr|) / 2
    cases = [
        (HexCoord(0, 0), HexCoord(3, 0), 3),
        (HexCoord(0, 0), HexCoord(2, -2), 2),
        (HexCoord(-1, 4), HexCoord(3, -1), 5),
        # (-3,-3) to (3,3): both axes step SE-ish, so this is *not* a
        # diagonal that cancels in cube distance; cube delta is
        # (6, 6, -12), giving distance 12.
        (HexCoord(-3, -3), HexCoord(3, 3), 12),
    ]
    for a, b, expected in cases:
        assert distance(a, b) == expected, (a, b, expected)
        assert distance(b, a) == expected, "distance is symmetric"


def test_distance_random_consistency_with_neighbours() -> None:
    rng = random.Random(42)
    origin = HexCoord(0, 0)
    for _ in range(50):
        # walk a known number of neighbour steps; resulting distance
        # must be at most that number (could be less if we backtrack).
        cur = origin
        steps = rng.randint(1, 8)
        for _ in range(steps):
            cur = rng.choice(neighbors(cur))
        assert distance(origin, cur) <= steps


# ---------------------------------------------------------------------------
# Line
# ---------------------------------------------------------------------------


def test_line_endpoints_included() -> None:
    a = HexCoord(0, 0)
    b = HexCoord(3, -1)
    pts = line(a, b)
    assert pts[0] == a
    assert pts[-1] == b


def test_line_length_equals_distance_plus_one() -> None:
    a = HexCoord(-2, 3)
    b = HexCoord(4, -1)
    assert len(line(a, b)) == distance(a, b) + 1


def test_line_continuous_steps() -> None:
    a = HexCoord(0, 0)
    b = HexCoord(4, -2)
    pts = line(a, b)
    for prev, curr in zip(pts, pts[1:]):
        assert distance(prev, curr) == 1, (prev, curr)


# ---------------------------------------------------------------------------
# Ring
# ---------------------------------------------------------------------------


def test_ring_radius_zero_is_center() -> None:
    c = HexCoord(2, 2)
    assert ring(c, 0) == [c]


def test_ring_radius_one_equals_neighbors() -> None:
    c = HexCoord(0, 0)
    assert set(ring(c, 1)) == set(neighbors(c))
    assert len(ring(c, 1)) == 6


def test_ring_radius_two_count_is_twelve() -> None:
    c = HexCoord(0, 0)
    r2 = ring(c, 2)
    assert len(r2) == 12
    for h in r2:
        assert distance(c, h) == 2


def test_ring_radius_three_count_is_eighteen() -> None:
    # General formula: 6 * radius for radius >= 1
    c = HexCoord(0, 0)
    assert len(ring(c, 3)) == 18


# ---------------------------------------------------------------------------
# Pixel conversion (flat-top)
# ---------------------------------------------------------------------------


def test_to_pixel_origin_zero_zero() -> None:
    x, y = to_pixel(HexCoord(0, 0), size=10.0)
    assert math.isclose(x, 0.0)
    assert math.isclose(y, 0.0)


def test_to_pixel_axial_stagger() -> None:
    # Flat-top axial:
    #   x = size * 3/2 * q
    #   y = size * (sqrt(3)/2 * q + sqrt(3) * r)
    s = 10.0
    cases = [
        (HexCoord(1, 0), s * 1.5, s * math.sqrt(3) / 2),
        (HexCoord(0, 1), 0.0, s * math.sqrt(3)),
        (HexCoord(2, 0), s * 3.0, s * math.sqrt(3)),
        (HexCoord(1, 1), s * 1.5, s * math.sqrt(3) * 1.5),
    ]
    for c, ex, ey in cases:
        x, y = to_pixel(c, s)
        assert math.isclose(x, ex), (c, x, ex)
        assert math.isclose(y, ey), (c, y, ey)


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_in_bounds_helper() -> None:
    assert in_bounds(HexCoord(0, 0), 8, 8)
    assert in_bounds(HexCoord(7, 7), 8, 8)
    assert not in_bounds(HexCoord(-1, 0), 8, 8)
    assert not in_bounds(HexCoord(0, -1), 8, 8)
    assert not in_bounds(HexCoord(8, 0), 8, 8)
    assert not in_bounds(HexCoord(0, 8), 8, 8)

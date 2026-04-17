"""Tests for river routing through sub-hex flowers.

Milestone M4: route_river_through_flower() in _flowers.py.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
    SubHexCell,
    EDGE_TO_RING2,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import route_river_through_flower


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub_cells(biome: Biome = Biome.GREENLANDS) -> dict[HexCoord, SubHexCell]:
    return {
        c: SubHexCell(coord=c, biome=biome, elevation=0.3)
        for c in FLOWER_COORDS
    }


# ---------------------------------------------------------------------------
# N-to-S river
# ---------------------------------------------------------------------------


def test_river_n_to_s_produces_path() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    assert len(path) >= 3, "path must cross at least 3 sub-hexes"


def test_river_n_to_s_starts_at_edge0() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    edge0_hexes = set(EDGE_TO_RING2[0])
    assert path[0] in edge0_hexes


def test_river_n_to_s_ends_at_edge3() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    edge3_hexes = set(EDGE_TO_RING2[3])
    assert path[-1] in edge3_hexes


# ---------------------------------------------------------------------------
# Path validity
# ---------------------------------------------------------------------------


def test_river_all_coords_in_flower() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    for c in path:
        assert c in FLOWER_COORDS, f"{c} not in flower"


def test_river_path_is_contiguous() -> None:
    """Each consecutive pair in the path must be neighbors."""
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    for a, b in zip(path, path[1:]):
        assert distance(a, b) == 1, f"{a} → {b} not adjacent"


def test_river_path_has_no_duplicates() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    assert len(path) == len(set(path))


# ---------------------------------------------------------------------------
# Multiple edge pairs
# ---------------------------------------------------------------------------


def test_river_ne_to_sw() -> None:
    cells = _make_sub_cells()
    rng = random.Random(99)
    path = route_river_through_flower(
        cells, entry_edge=1, exit_edge=4, rng=rng,
    )
    assert path[0] in set(EDGE_TO_RING2[1])
    assert path[-1] in set(EDGE_TO_RING2[4])
    for a, b in zip(path, path[1:]):
        assert distance(a, b) == 1


def test_river_se_to_nw() -> None:
    cells = _make_sub_cells()
    rng = random.Random(77)
    path = route_river_through_flower(
        cells, entry_edge=2, exit_edge=5, rng=rng,
    )
    assert path[0] in set(EDGE_TO_RING2[2])
    assert path[-1] in set(EDGE_TO_RING2[5])
    for a, b in zip(path, path[1:]):
        assert distance(a, b) == 1


def test_river_adjacent_edges() -> None:
    """River entering edge 0 and exiting edge 1 (adjacent)."""
    cells = _make_sub_cells()
    rng = random.Random(33)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=1, rng=rng,
    )
    assert path[0] in set(EDGE_TO_RING2[0])
    assert path[-1] in set(EDGE_TO_RING2[1])
    for a, b in zip(path, path[1:]):
        assert distance(a, b) == 1


# ---------------------------------------------------------------------------
# Source river (entry=None)
# ---------------------------------------------------------------------------


def test_river_source_starts_at_ring1() -> None:
    """A river source (entry_edge=None) starts at a ring-1 sub-hex."""
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=None, exit_edge=3, rng=rng,
    )
    center = HexCoord(0, 0)
    assert distance(center, path[0]) == 1, (
        f"source should start at ring 1, got {path[0]}"
    )


def test_river_source_ends_at_correct_edge() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=None, exit_edge=3, rng=rng,
    )
    assert path[-1] in set(EDGE_TO_RING2[3])


# ---------------------------------------------------------------------------
# Sink river (exit=None)
# ---------------------------------------------------------------------------


def test_river_sink_ends_at_ring1() -> None:
    """A river sink (exit_edge=None) ends at a ring-1 sub-hex."""
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=None, rng=rng,
    )
    center = HexCoord(0, 0)
    assert distance(center, path[-1]) == 1, (
        f"sink should end at ring 1, got {path[-1]}"
    )


def test_river_sink_starts_at_correct_edge() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=None, rng=rng,
    )
    assert path[0] in set(EDGE_TO_RING2[0])


# ---------------------------------------------------------------------------
# has_river flag
# ---------------------------------------------------------------------------


def test_river_marks_crossed_sub_hexes() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_river_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
        mark_cells=True,
    )
    for c in path:
        assert cells[c].has_river is True
    # Non-path cells should not be marked
    for c in FLOWER_COORDS:
        if c not in path:
            assert cells[c].has_river is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_river_deterministic() -> None:
    cells1 = _make_sub_cells()
    rng1 = random.Random(555)
    path1 = route_river_through_flower(
        cells1, entry_edge=0, exit_edge=3, rng=rng1,
    )
    cells2 = _make_sub_cells()
    rng2 = random.Random(555)
    path2 = route_river_through_flower(
        cells2, entry_edge=0, exit_edge=3, rng=rng2,
    )
    assert path1 == path2


# ---------------------------------------------------------------------------
# Center avoidance
# ---------------------------------------------------------------------------


def test_river_avoids_center() -> None:
    """Rivers should avoid the hex center (ring 0) so they don't
    obscure feature icons."""
    center = HexCoord(0, 0)
    # Run many seeds; the center should rarely appear in the path.
    center_count = 0
    for seed in range(50):
        cells = _make_sub_cells()
        rng = random.Random(seed)
        path = route_river_through_flower(
            cells, entry_edge=0, exit_edge=3, rng=rng,
        )
        if center in path:
            center_count += 1
    assert center_count < 10, (
        f"river should avoid center most of the time, "
        f"but crossed it {center_count}/50 times"
    )

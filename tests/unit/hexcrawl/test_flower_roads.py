"""Tests for road routing through sub-hex flowers.

Milestone M5: route_road_through_flower() in _flowers.py.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.model import (
    Biome,
    HexFeatureType,
    SubHexCell,
    EDGE_TO_RING2,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import route_road_through_flower


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub_cells(biome: Biome = Biome.GREENLANDS) -> dict[HexCoord, SubHexCell]:
    return {
        c: SubHexCell(coord=c, biome=biome, move_cost_hours=1.0)
        for c in FLOWER_COORDS
    }


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------


def test_road_n_to_s_produces_path() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    assert len(path) >= 3


def test_road_starts_and_ends_at_correct_edges() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=1, exit_edge=4, rng=rng,
    )
    assert path[0] in set(EDGE_TO_RING2[1])
    assert path[-1] in set(EDGE_TO_RING2[4])


def test_road_path_is_contiguous() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    for a, b in zip(path, path[1:]):
        assert distance(a, b) == 1, f"{a} → {b} not adjacent"


def test_road_all_coords_in_flower() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
    )
    for c in path:
        assert c in FLOWER_COORDS


# ---------------------------------------------------------------------------
# Road prefers feature cell
# ---------------------------------------------------------------------------


def test_road_passes_through_feature_cell() -> None:
    """When a feature_cell is provided and on a reasonable route,
    the road should prefer to pass through it."""
    feature_coord = HexCoord(0, 0)  # center
    cells = _make_sub_cells()
    # Run many seeds; the road should hit the feature most of the time
    hit_count = 0
    for seed in range(50):
        rng = random.Random(seed)
        path = route_road_through_flower(
            cells, entry_edge=0, exit_edge=3, rng=rng,
            feature_cell=feature_coord,
        )
        if feature_coord in path:
            hit_count += 1
    assert hit_count > 35, (
        f"road should pass through feature cell most of the time, "
        f"but only hit {hit_count}/50"
    )


# ---------------------------------------------------------------------------
# has_road flag and move cost
# ---------------------------------------------------------------------------


def test_road_marks_has_road() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
        mark_cells=True,
    )
    for c in path:
        assert cells[c].has_road is True
    for c in FLOWER_COORDS:
        if c not in path:
            assert cells[c].has_road is False


def test_road_halves_move_cost() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
        mark_cells=True,
    )
    for c in path:
        assert cells[c].move_cost_hours == 0.5, (
            f"road sub-hex {c} should have halved cost"
        )


def test_road_cost_minimum_is_half() -> None:
    """Road cost on a biome that already has 1.0 cost becomes 0.5."""
    cells = _make_sub_cells(Biome.GREENLANDS)
    rng = random.Random(42)
    path = route_road_through_flower(
        cells, entry_edge=0, exit_edge=3, rng=rng,
        mark_cells=True,
    )
    for c in path:
        assert cells[c].move_cost_hours >= 0.5


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_road_deterministic() -> None:
    cells1 = _make_sub_cells()
    rng1 = random.Random(555)
    path1 = route_road_through_flower(
        cells1, entry_edge=0, exit_edge=3, rng=rng1,
    )
    cells2 = _make_sub_cells()
    rng2 = random.Random(555)
    path2 = route_road_through_flower(
        cells2, entry_edge=0, exit_edge=3, rng=rng2,
    )
    assert path1 == path2

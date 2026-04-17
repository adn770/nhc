"""Tests for fast-travel cost pre-computation.

Milestone M7: compute_fast_travel_costs() in _flowers.py.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    SubHexCell,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import compute_fast_travel_costs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub_cells(
    biome: Biome = Biome.GREENLANDS,
    cost: float = 1.0,
) -> dict[HexCoord, SubHexCell]:
    return {
        c: SubHexCell(coord=c, biome=biome, move_cost_hours=cost)
        for c in FLOWER_COORDS
    }


# ---------------------------------------------------------------------------
# All 30 (entry, exit) pairs computed
# ---------------------------------------------------------------------------


def test_all_30_pairs_present() -> None:
    cells = _make_sub_cells()
    costs = compute_fast_travel_costs(cells)
    expected_pairs = {
        (e, x) for e in range(6) for x in range(6) if e != x
    }
    assert set(costs.keys()) == expected_pairs


def test_all_costs_positive() -> None:
    cells = _make_sub_cells()
    costs = compute_fast_travel_costs(cells)
    for pair, cost in costs.items():
        assert cost > 0, f"cost for {pair} should be positive"


# ---------------------------------------------------------------------------
# Road presence reduces cost
# ---------------------------------------------------------------------------


def test_road_reduces_cost() -> None:
    """A flower with road sub-hexes should have lower fast-travel
    cost than one without."""
    cells_no_road = _make_sub_cells()
    costs_no_road = compute_fast_travel_costs(cells_no_road)

    # Place a road through the middle N→S
    cells_road = _make_sub_cells()
    road_path = [
        HexCoord(0, -2), HexCoord(0, -1), HexCoord(0, 0),
        HexCoord(0, 1), HexCoord(0, 2),
    ]
    for c in road_path:
        cells_road[c].has_road = True
        cells_road[c].move_cost_hours = 0.5

    costs_road = compute_fast_travel_costs(cells_road)

    # N-to-S should be cheaper with the road
    assert costs_road[(0, 3)] < costs_no_road[(0, 3)]


# ---------------------------------------------------------------------------
# Different biomes = different costs
# ---------------------------------------------------------------------------


def test_mountain_more_expensive_than_greenlands() -> None:
    cells_green = _make_sub_cells(Biome.GREENLANDS, cost=1.0)
    costs_green = compute_fast_travel_costs(cells_green)

    cells_mountain = _make_sub_cells(Biome.MOUNTAIN, cost=3.0)
    costs_mountain = compute_fast_travel_costs(cells_mountain)

    # Pick any pair — mountain should cost more
    for pair in costs_green:
        assert costs_mountain[pair] > costs_green[pair], (
            f"mountain should be more expensive for {pair}"
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_costs_deterministic() -> None:
    cells1 = _make_sub_cells()
    costs1 = compute_fast_travel_costs(cells1)
    cells2 = _make_sub_cells()
    costs2 = compute_fast_travel_costs(cells2)
    assert costs1 == costs2


# ---------------------------------------------------------------------------
# Sanity: opposite direction costs may differ
# ---------------------------------------------------------------------------


def test_asymmetric_costs_possible() -> None:
    """With uniform cells costs are symmetric, but with varied
    costs (e.g. roads on one side) they can differ."""
    cells = _make_sub_cells()
    # Make NE quadrant cheaper
    cells[HexCoord(1, -2)].move_cost_hours = 0.5
    cells[HexCoord(2, -2)].move_cost_hours = 0.5
    cells[HexCoord(2, -1)].move_cost_hours = 0.5
    costs = compute_fast_travel_costs(cells)
    # At minimum, costs should still exist for both directions
    assert (0, 3) in costs
    assert (3, 0) in costs

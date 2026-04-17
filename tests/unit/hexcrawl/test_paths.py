"""Tests for path generation.

Paths connect settlements (cities, villages) and optionally
towers/caves via A* over the hex grid. Each hex along a path
carries an EdgeSegment with consistent entry/exit edges.
"""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl._paths import (
    hex_astar,
    generate_paths,
    PathParams,
)
from nhc.hexcrawl._rivers import direction_index
from nhc.hexcrawl.pack import DEFAULT_BIOME_COSTS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cells(
    width: int = 8,
    height: int = 8,
    biome: Biome = Biome.GREENLANDS,
) -> dict[HexCoord, HexCell]:
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=biome,
                elevation=0.3,
            )
    return cells


def _place_feature(
    cells: dict[HexCoord, HexCell],
    coord: HexCoord,
    feature: HexFeatureType,
) -> None:
    cells[coord].feature = feature
    if feature in (HexFeatureType.CITY, HexFeatureType.VILLAGE):
        cells[coord].dungeon = DungeonRef(template="procedural:settlement")
    elif feature is HexFeatureType.TOWER:
        cells[coord].dungeon = DungeonRef(template="procedural:tower")
    elif feature is HexFeatureType.CAVE:
        cells[coord].dungeon = DungeonRef(template="procedural:cave")


# ---------------------------------------------------------------------------
# hex_astar
# ---------------------------------------------------------------------------


def test_astar_finds_straight_path() -> None:
    cells = _make_cells(8, 8)
    start = HexCoord(0, 0)
    goal = HexCoord(0, 4)
    path = hex_astar(start, goal, cells, DEFAULT_BIOME_COSTS)
    assert len(path) >= 2
    assert path[0] == start
    assert path[-1] == goal


def test_astar_avoids_water() -> None:
    cells = _make_cells(8, 8)
    # Wall of water at r=2 (except q=0).
    for q in range(1, 8):
        cells[HexCoord(q, 2)].biome = Biome.WATER
    start = HexCoord(4, 0)
    goal = HexCoord(4, 4)
    path = hex_astar(start, goal, cells, DEFAULT_BIOME_COSTS)
    if path:
        for coord in path:
            assert cells[coord].biome is not Biome.WATER


def test_astar_returns_empty_when_unreachable() -> None:
    cells = _make_cells(6, 6)
    # Surround the goal with water.
    goal = HexCoord(3, 3)
    for n in neighbors(goal):
        if n in cells:
            cells[n].biome = Biome.WATER
    path = hex_astar(HexCoord(0, 0), goal, cells, DEFAULT_BIOME_COSTS)
    assert path == []


def test_astar_same_start_and_goal() -> None:
    cells = _make_cells(4, 4)
    path = hex_astar(HexCoord(2, 2), HexCoord(2, 2), cells, DEFAULT_BIOME_COSTS)
    assert path == [HexCoord(2, 2)]


# ---------------------------------------------------------------------------
# generate_paths
# ---------------------------------------------------------------------------


def test_paths_connect_settlements() -> None:
    cells = _make_cells(10, 10)
    _place_feature(cells, HexCoord(1, 1), HexFeatureType.CITY)
    _place_feature(cells, HexCoord(7, 7), HexFeatureType.VILLAGE)
    params = PathParams(connect_towers=0.0, connect_caves=0.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    assert len(paths) >= 1
    # Path should touch both settlement hexes.
    all_coords = {c for path in paths for c in path}
    assert HexCoord(1, 1) in all_coords
    assert HexCoord(7, 7) in all_coords


def test_paths_edge_segments_consistent() -> None:
    """Exit edge of path[i] matches entry edge of path[i+1]."""
    cells = _make_cells(8, 8)
    _place_feature(cells, HexCoord(0, 0), HexFeatureType.CITY)
    _place_feature(cells, HexCoord(6, 6), HexFeatureType.VILLAGE)
    params = PathParams(connect_towers=0.0, connect_caves=0.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    for path in paths:
        for i in range(len(path) - 1):
            cur_segs = [
                s for s in cells[path[i]].edges if s.type == "path"
            ]
            nxt_segs = [
                s for s in cells[path[i + 1]].edges if s.type == "path"
            ]
            assert cur_segs, f"no path segment on {path[i]}"
            assert nxt_segs, f"no path segment on {path[i + 1]}"
            cur_exit = cur_segs[0].exit_edge
            nxt_entry = nxt_segs[0].entry_edge
            if cur_exit is not None and nxt_entry is not None:
                assert nxt_entry == (cur_exit + 3) % 6


def test_paths_avoid_water_tiles() -> None:
    cells = _make_cells(10, 10)
    _place_feature(cells, HexCoord(0, 0), HexFeatureType.CITY)
    _place_feature(cells, HexCoord(9, 9), HexFeatureType.VILLAGE)
    # Put some water in the middle.
    for q in range(3, 7):
        cells[HexCoord(q, 5)].biome = Biome.WATER
    params = PathParams(connect_towers=0.0, connect_caves=0.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    for path in paths:
        for coord in path:
            assert cells[coord].biome is not Biome.WATER


def test_paths_deterministic() -> None:
    cells_a = _make_cells(8, 8)
    cells_b = _make_cells(8, 8)
    for c in (cells_a, cells_b):
        _place_feature(c, HexCoord(0, 0), HexFeatureType.CITY)
        _place_feature(c, HexCoord(6, 6), HexFeatureType.VILLAGE)
    params = PathParams(connect_towers=0.0, connect_caves=0.0)
    paths_a = generate_paths(cells_a, random.Random(99), params, DEFAULT_BIOME_COSTS)
    paths_b = generate_paths(cells_b, random.Random(99), params, DEFAULT_BIOME_COSTS)
    assert paths_a == paths_b


def test_no_settlements_produces_no_paths() -> None:
    cells = _make_cells(4, 4)
    params = PathParams()
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    assert paths == []


def test_single_settlement_no_paths() -> None:
    cells = _make_cells(4, 4)
    _place_feature(cells, HexCoord(2, 2), HexFeatureType.CITY)
    params = PathParams(connect_towers=0.0, connect_caves=0.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    assert paths == []


def test_tower_connected_with_high_probability() -> None:
    """With connect_towers=1.0, every tower gets a path."""
    cells = _make_cells(10, 10)
    _place_feature(cells, HexCoord(1, 1), HexFeatureType.CITY)
    _place_feature(cells, HexCoord(8, 1), HexFeatureType.TOWER)
    params = PathParams(connect_towers=1.0, connect_caves=0.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    all_coords = {c for path in paths for c in path}
    assert HexCoord(8, 1) in all_coords


def test_cave_connected_with_high_probability() -> None:
    """With connect_caves=1.0, every cave gets a path."""
    cells = _make_cells(10, 10)
    _place_feature(cells, HexCoord(1, 1), HexFeatureType.CITY)
    _place_feature(cells, HexCoord(8, 8), HexFeatureType.CAVE)
    params = PathParams(connect_towers=0.0, connect_caves=1.0)
    rng = random.Random(42)
    paths = generate_paths(cells, rng, params, DEFAULT_BIOME_COSTS)
    all_coords = {c for path in paths for c in path}
    assert HexCoord(8, 8) in all_coords

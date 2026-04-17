"""Tests for sub-hex biome assignment with edge blending.

Milestone M3: assign_sub_hex_biomes() in _flowers.py.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    FLOWER_COORDS,
    FLOWER_RADIUS,
)
from nhc.hexcrawl._flowers import assign_sub_hex_biomes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cells_uniform(
    biome: Biome,
    width: int = 5,
    height: int = 5,
) -> dict[HexCoord, HexCell]:
    """Build a small uniform-biome grid centered near (2, 2)."""
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=biome,
                elevation=0.3,
            )
    return cells


def _make_cells_mixed() -> dict[HexCoord, HexCell]:
    """Build a grid where center is FOREST and the N neighbor
    is MOUNTAIN, rest FOREST."""
    cells = _make_cells_uniform(Biome.FOREST)
    # Make the hex at (2, 1) a different biome (N neighbor of (2, 2))
    cells[HexCoord(2, 1)] = HexCell(
        coord=HexCoord(2, 1),
        biome=Biome.MOUNTAIN,
        elevation=0.8,
    )
    return cells


# ---------------------------------------------------------------------------
# Ring 0 always inherits parent
# ---------------------------------------------------------------------------


def test_ring0_inherits_parent_biome() -> None:
    cells = _make_cells_uniform(Biome.FOREST)
    parent = cells[HexCoord(2, 2)]
    rng = random.Random(42)
    sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
    center = HexCoord(0, 0)
    assert sub_biomes[center] == Biome.FOREST


def test_ring0_inherits_for_all_biomes() -> None:
    """Ring 0 inherits parent regardless of biome type."""
    for biome in Biome:
        if biome is Biome.WATER:
            continue
        cells = _make_cells_uniform(biome)
        parent = cells[HexCoord(2, 2)]
        rng = random.Random(99)
        sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
        assert sub_biomes[HexCoord(0, 0)] == biome


# ---------------------------------------------------------------------------
# Ring 1 mostly inherits parent
# ---------------------------------------------------------------------------


def test_ring1_mostly_parent_biome() -> None:
    """Over many seeds, ring-1 sub-hexes are >80% parent biome."""
    cells = _make_cells_uniform(Biome.FOREST)
    parent = cells[HexCoord(2, 2)]
    ring1_coords = [c for c in FLOWER_COORDS if distance(HexCoord(0, 0), c) == 1]
    parent_count = 0
    total = 0
    for seed in range(100):
        rng = random.Random(seed)
        sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
        for c in ring1_coords:
            total += 1
            if sub_biomes[c] == Biome.FOREST:
                parent_count += 1
    assert parent_count / total > 0.80


# ---------------------------------------------------------------------------
# Ring 2 blends toward neighbor biomes
# ---------------------------------------------------------------------------


def test_ring2_produces_some_blended_biomes() -> None:
    """When neighbor has a different biome, some ring-2 sub-hexes
    should pick up that biome over many seeds."""
    cells = _make_cells_mixed()
    parent = cells[HexCoord(2, 2)]
    ring2_coords = [c for c in FLOWER_COORDS if distance(HexCoord(0, 0), c) == 2]
    non_parent_count = 0
    total = 0
    for seed in range(200):
        rng = random.Random(seed)
        sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
        for c in ring2_coords:
            total += 1
            if sub_biomes[c] != Biome.FOREST:
                non_parent_count += 1
    assert non_parent_count > 0, "expected some blended sub-hexes"


def test_ring2_uniform_neighbors_stays_parent() -> None:
    """When all neighbors share the parent biome, ring-2 sub-hexes
    should overwhelmingly stay parent (>95%)."""
    cells = _make_cells_uniform(Biome.GREENLANDS)
    parent = cells[HexCoord(2, 2)]
    ring2_coords = [c for c in FLOWER_COORDS if distance(HexCoord(0, 0), c) == 2]
    parent_count = 0
    total = 0
    for seed in range(100):
        rng = random.Random(seed)
        sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
        for c in ring2_coords:
            total += 1
            if sub_biomes[c] == Biome.GREENLANDS:
                parent_count += 1
    assert parent_count / total > 0.95


# ---------------------------------------------------------------------------
# Edge case: map border (missing neighbor)
# ---------------------------------------------------------------------------


def test_ring2_at_map_edge_stays_parent() -> None:
    """Ring-2 sub-hexes facing off-map stay parent biome."""
    # Only populate the center hex, no neighbors
    parent = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.ICELANDS,
        elevation=0.1,
    )
    cells = {parent.coord: parent}
    ring2_coords = [c for c in FLOWER_COORDS if distance(HexCoord(0, 0), c) == 2]
    for seed in range(50):
        rng = random.Random(seed)
        sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
        for c in ring2_coords:
            assert sub_biomes[c] == Biome.ICELANDS, (
                f"seed {seed}: ring-2 {c} should stay ICELANDS "
                f"at map edge, got {sub_biomes[c]}"
            )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_with_same_seed() -> None:
    cells = _make_cells_mixed()
    parent = cells[HexCoord(2, 2)]
    rng1 = random.Random(12345)
    result1 = assign_sub_hex_biomes(parent, cells, rng1)
    rng2 = random.Random(12345)
    result2 = assign_sub_hex_biomes(parent, cells, rng2)
    assert result1 == result2


# ---------------------------------------------------------------------------
# All 19 coords returned
# ---------------------------------------------------------------------------


def test_returns_all_flower_coords() -> None:
    cells = _make_cells_uniform(Biome.DRYLANDS)
    parent = cells[HexCoord(2, 2)]
    rng = random.Random(0)
    sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
    assert set(sub_biomes.keys()) == FLOWER_COORDS


# ---------------------------------------------------------------------------
# Water biome hex produces all-water flower
# ---------------------------------------------------------------------------


def test_water_hex_produces_all_water() -> None:
    cells = _make_cells_uniform(Biome.WATER)
    parent = cells[HexCoord(2, 2)]
    rng = random.Random(0)
    sub_biomes = assign_sub_hex_biomes(parent, cells, rng)
    for c in FLOWER_COORDS:
        assert sub_biomes[c] == Biome.WATER

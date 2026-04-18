"""Tests for feature pattern placement."""

import random

from nhc.dungeon.generator import Range
from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.patterns import (
    CAVES_OF_CHAOS,
    PATTERNS,
    FeaturePattern,
    SatelliteSpec,
    place_pattern,
)


def _make_cells(
    width: int = 8, height: int = 8,
    biome: Biome = Biome.GREENLANDS,
) -> dict[HexCoord, HexCell]:
    """Create a flat grid of hex cells for testing."""
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=biome,
            )
    return cells


class TestPatternRegistry:
    def test_caves_of_chaos_registered(self):
        assert "caves_of_chaos" in PATTERNS

    def test_caves_of_chaos_structure(self):
        p = CAVES_OF_CHAOS
        assert p.anchor_feature == HexFeatureType.KEEP
        assert len(p.satellite_specs) >= 1
        sat = p.satellite_specs[0]
        assert sat.feature == HexFeatureType.CAVE
        assert sat.count.min >= 3
        assert sat.faction_pool is not None
        assert len(sat.faction_pool) >= 5


class TestPlacePattern:
    def test_places_anchor_and_satellites(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        ok = place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))
        assert ok

        # Find the anchor
        keeps = [
            (c, cell) for c, cell in cells.items()
            if cell.feature == HexFeatureType.KEEP
        ]
        assert len(keeps) == 1
        anchor_coord = keeps[0][0]

        # Find satellites
        caves = [
            (c, cell) for c, cell in cells.items()
            if cell.feature == HexFeatureType.CAVE
        ]
        assert len(caves) >= 3

    def test_satellites_within_distance(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))

        keeps = [
            c for c, cell in cells.items()
            if cell.feature == HexFeatureType.KEEP
        ]
        anchor = keeps[0]
        caves = [
            c for c, cell in cells.items()
            if cell.feature == HexFeatureType.CAVE
        ]
        for cave_coord in caves:
            assert distance(anchor, cave_coord) <= 2

    def test_factions_assigned(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))

        caves = [
            cell for cell in cells.values()
            if cell.feature == HexFeatureType.CAVE
        ]
        factions = [cell.dungeon.faction for cell in caves]
        assert all(f is not None for f in factions)
        # Factions should be distinct
        assert len(set(factions)) == len(factions)

    def test_factions_from_pool(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))

        valid_factions = {
            "goblin", "orc", "kobold", "gnoll", "bugbear", "ogre",
        }
        caves = [
            cell for cell in cells.values()
            if cell.feature == HexFeatureType.CAVE
        ]
        for cell in caves:
            assert cell.dungeon.faction in valid_factions

    def test_anchor_has_keep_template(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))

        keeps = [
            cell for cell in cells.values()
            if cell.feature == HexFeatureType.KEEP
        ]
        assert keeps[0].dungeon.template == "procedural:keep"

    def test_returns_false_when_no_space(self):
        """Pattern fails gracefully when there's no room."""
        cells = _make_cells(width=2, height=2)
        # Fill all cells
        taken = set(cells.keys())
        ok = place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))
        assert not ok

    def test_taken_cells_updated(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        place_pattern(CAVES_OF_CHAOS, cells, taken, random.Random(42))
        # Anchor + satellites should be in taken
        assert len(taken) >= 4  # 1 keep + 3+ caves

"""Tests for FeaturePattern integration in place_features."""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.model import Biome, HexCell, HexFeatureType
from nhc.hexcrawl._features import _place_patterns


def _make_cells(
    width: int = 10, height: int = 10,
    biome: Biome = Biome.GREENLANDS,
) -> dict[HexCoord, HexCell]:
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r), biome=biome,
            )
    return cells


class TestPlacePatterns:
    def test_places_caves_of_chaos_by_default(self):
        """With no overrides, the default pattern set includes CoC."""
        cells = _make_cells()
        taken: set[HexCoord] = set()
        rng = random.Random(42)
        placed = _place_patterns(cells, taken, rng)

        keeps = [
            c for c, cell in cells.items()
            if cell.feature == HexFeatureType.KEEP
        ]
        assert len(keeps) == 1
        anchor = keeps[0]
        caves = [
            c for c, cell in cells.items()
            if cell.feature == HexFeatureType.CAVE
        ]
        assert len(caves) >= 3
        for cave in caves:
            assert distance(anchor, cave) <= 2
        # Budget returned: 1 KEEP + N caves
        assert placed == 1 + len(caves)

    def test_disabled_pattern_list_skips_placement(self):
        """Passing an empty pattern list disables all patterns."""
        cells = _make_cells()
        taken: set[HexCoord] = set()
        rng = random.Random(42)
        placed = _place_patterns(
            cells, taken, rng, enabled_patterns=[],
        )

        assert placed == 0
        assert not any(
            cell.feature == HexFeatureType.KEEP for cell in cells.values()
        )
        assert not any(
            cell.feature == HexFeatureType.CAVE for cell in cells.values()
        )

    def test_taken_cells_updated(self):
        cells = _make_cells()
        taken: set[HexCoord] = set()
        rng = random.Random(42)
        _place_patterns(cells, taken, rng)
        assert len(taken) >= 4  # 1 keep + 3+ caves

    def test_deterministic_with_seed(self):
        cells_a = _make_cells()
        cells_b = _make_cells()
        taken_a: set[HexCoord] = set()
        taken_b: set[HexCoord] = set()
        _place_patterns(cells_a, taken_a, random.Random(123))
        _place_patterns(cells_b, taken_b, random.Random(123))
        feats_a = {
            c: cell.feature for c, cell in cells_a.items()
            if cell.feature is not HexFeatureType.NONE
        }
        feats_b = {
            c: cell.feature for c, cell in cells_b.items()
            if cell.feature is not HexFeatureType.NONE
        }
        assert feats_a == feats_b

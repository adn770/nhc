"""Tests for the v2 settlement placement module."""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import HexCoord, neighbors, shape_r_range
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import FeatureTarget, FeatureTargets


# ---------------------------------------------------------------------------
# Test cells builder
# ---------------------------------------------------------------------------


def _build_scored_cells() -> dict[HexCoord, HexCell]:
    """Build a 10x8 grid with varied biomes for scoring tests."""
    cells: dict[HexCoord, HexCell] = {}
    width, height = 10, 8
    for q in range(width):
        r_min, r_max = shape_r_range(q, height)
        for r in range(r_min, r_max):
            coord = HexCoord(q, r)
            if q <= 3:
                biome = Biome.GREENLANDS
            elif q <= 5:
                biome = Biome.FOREST
            elif q <= 7:
                biome = Biome.HILLS
            else:
                biome = Biome.DRYLANDS
            cells[coord] = HexCell(
                coord=coord, biome=biome,
                elevation=0.30 - q * 0.02,
            )
    return cells


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------


class TestSettlementScore:

    def test_river_adjacent_higher(self) -> None:
        from nhc.hexcrawl._features_scored import settlement_score

        cells = _build_scored_cells()
        h = HexCoord(2, 0)
        score_no_river = settlement_score(h, cells)

        # Add a river to this hex
        cells[h].edges.append(
            EdgeSegment(type="river", entry_edge=0, exit_edge=3),
        )
        score_with_river = settlement_score(h, cells)
        assert score_with_river > score_no_river

    def test_biome_border_higher(self) -> None:
        from nhc.hexcrawl._features_scored import settlement_score

        cells = _build_scored_cells()
        # Interior greenlands hex (all neighbors also greenlands)
        interior = HexCoord(1, 0)
        # Border hex (at biome boundary greenlands/forest)
        border = HexCoord(3, 0)

        score_interior = settlement_score(interior, cells)
        score_border = settlement_score(border, cells)
        assert score_border > score_interior

    def test_lake_adjacent_higher(self) -> None:
        from nhc.hexcrawl._features_scored import settlement_score

        cells = _build_scored_cells()
        h = HexCoord(2, 0)
        score_no_lake = settlement_score(h, cells)

        # Put a lake adjacent
        nbr = neighbors(h)[0]
        if nbr in cells:
            cells[nbr].feature = HexFeatureType.LAKE
        score_with_lake = settlement_score(h, cells)
        assert score_with_lake > score_no_lake

    def test_greenlands_scores_higher_than_swamp(self) -> None:
        from nhc.hexcrawl._features_scored import settlement_score

        cells = _build_scored_cells()
        h = HexCoord(2, 0)
        score_green = settlement_score(h, cells)

        cells[h].biome = Biome.SWAMP
        score_swamp = settlement_score(h, cells)
        assert score_green > score_swamp


# ---------------------------------------------------------------------------
# Placement tests
# ---------------------------------------------------------------------------


class TestSettlementPlacement:

    def test_spacing(self) -> None:
        from nhc.hexcrawl._features_scored import place_settlements

        cells = _build_scored_cells()
        targets = FeatureTargets(
            hub=1,
            village=FeatureTarget(2, 4),
            dungeon=FeatureTarget(0, 0),
            wonder=FeatureTarget(0, 0),
        )
        rng = random.Random(42)
        place_settlements(cells, targets, rng)

        settlements = [
            c for c, cell in cells.items()
            if cell.feature in (
                HexFeatureType.VILLAGE, HexFeatureType.CITY,
            )
        ]
        # No two settlements should be adjacent
        for i, a in enumerate(settlements):
            for b in settlements[i + 1:]:
                nbrs_a = set(neighbors(a))
                assert b not in nbrs_a, (
                    f"settlements {a} and {b} are adjacent"
                )

    def test_hub_in_greenlands(self) -> None:
        from nhc.hexcrawl._features_scored import place_settlements

        cells = _build_scored_cells()
        targets = FeatureTargets(hub=1)
        rng = random.Random(42)
        hub = place_settlements(cells, targets, rng)

        assert hub is not None
        assert cells[hub].biome is Biome.GREENLANDS

    def test_count_within_targets(self) -> None:
        from nhc.hexcrawl._features_scored import place_settlements

        cells = _build_scored_cells()
        targets = FeatureTargets(
            hub=1,
            village=FeatureTarget(1, 3),
            dungeon=FeatureTarget(0, 0),
            wonder=FeatureTarget(0, 0),
        )
        rng = random.Random(42)
        place_settlements(cells, targets, rng)

        villages = sum(
            1 for c in cells.values()
            if c.feature is HexFeatureType.VILLAGE
        )
        # Village count (excluding hub city) within targets
        assert targets.village.min <= villages <= targets.village.max

    def test_deterministic(self) -> None:
        from nhc.hexcrawl._features_scored import place_settlements

        targets = FeatureTargets(
            hub=1,
            village=FeatureTarget(2, 4),
            dungeon=FeatureTarget(0, 0),
            wonder=FeatureTarget(0, 0),
        )
        cells_a = _build_scored_cells()
        hub_a = place_settlements(
            cells_a, targets, random.Random(42),
        )
        cells_b = _build_scored_cells()
        hub_b = place_settlements(
            cells_b, targets, random.Random(42),
        )
        assert hub_a == hub_b
        feats_a = {
            c: cell.feature for c, cell in cells_a.items()
            if cell.feature is not HexFeatureType.NONE
        }
        feats_b = {
            c: cell.feature for c, cell in cells_b.items()
            if cell.feature is not HexFeatureType.NONE
        }
        assert feats_a == feats_b

"""Tests for biome-aware feature placement (milestone 3).

The biome eligibility matrix from design/biome_features.md §3
is encoded as ``FEATURE_BIOMES`` and drives both place_features
and place_dungeons. Size classes are pinned by feature type
(no more random roll). Community and ruin counts come from the
new pack knobs.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from nhc.hexcrawl._features import (
    FEATURE_BIOMES,
    pick_hub,
    place_features,
)
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import (
    ContinentalParams,
    FeatureTarget,
    FeatureTargets,
    MapParams,
    PackMeta,
    DEFAULT_BIOME_COSTS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mixed_world(
    width: int = 12,
    height: int = 12,
) -> tuple[dict[HexCoord, HexCell], dict[Biome, list[HexCoord]]]:
    """Build a grid with every biome represented in a predictable band.

    Columns 0-1: GREENLANDS, 2-3: HILLS, 4-5: FOREST, 6-7: MOUNTAIN,
    8: SANDLANDS, 9: DRYLANDS, 10: MARSH, 11: ICELANDS / DEADLANDS.
    """
    cells: dict[HexCoord, HexCell] = {}
    hbb: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
    for q in range(width):
        for r in range(height):
            if q < 2:
                biome = Biome.GREENLANDS
            elif q < 4:
                biome = Biome.HILLS
            elif q < 6:
                biome = Biome.FOREST
            elif q < 8:
                biome = Biome.MOUNTAIN
            elif q == 8:
                biome = Biome.SANDLANDS
            elif q == 9:
                biome = Biome.DRYLANDS
            elif q == 10:
                biome = Biome.MARSH
            else:
                biome = Biome.ICELANDS if r % 2 == 0 else Biome.DEADLANDS
            coord = HexCoord(q, r)
            cells[coord] = HexCell(coord=coord, biome=biome)
            hbb[biome].append(coord)
    return cells, hbb


def _make_pack(
    village: tuple[int, int] = (1, 1),
    community: tuple[int, int] = (0, 0),
    dungeon: tuple[int, int] = (0, 0),
    ruin: tuple[int, int] = (0, 0),
    wonder: tuple[int, int] = (0, 0),
    patterns: list[str] | None = None,
) -> PackMeta:
    features = FeatureTargets(
        hub=1,
        village=FeatureTarget(*village),
        community=FeatureTarget(*community),
        dungeon=FeatureTarget(*dungeon),
        ruin=FeatureTarget(*ruin),
        wonder=FeatureTarget(*wonder),
        patterns=patterns if patterns is not None else [],
    )
    return PackMeta(
        id="test",
        version=1,
        attribution="test",
        map=MapParams(
            generator="continental",
            width=12, height=12,
            continental=ContinentalParams(),
        ),
        features=features,
        biome_costs=dict(DEFAULT_BIOME_COSTS),
    )


# ---------------------------------------------------------------------------
# FEATURE_BIOMES matrix
# ---------------------------------------------------------------------------


class TestFeatureBiomesMatrix:
    def test_city_places_on_greenlands_or_hills_only(self) -> None:
        assert set(FEATURE_BIOMES[HexFeatureType.CITY]) == {
            Biome.GREENLANDS, Biome.HILLS,
        }

    def test_village_pool_excludes_forest_and_deadlands(self) -> None:
        pool = set(FEATURE_BIOMES[HexFeatureType.VILLAGE])
        assert Biome.FOREST not in pool
        assert Biome.DEADLANDS not in pool
        assert Biome.ICELANDS not in pool
        # Includes the six eligible biomes from the matrix.
        assert pool == {
            Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
            Biome.DRYLANDS, Biome.MARSH, Biome.MOUNTAIN,
        }

    def test_community_pool_includes_forest(self) -> None:
        pool = set(FEATURE_BIOMES[HexFeatureType.COMMUNITY])
        assert Biome.FOREST in pool
        # Communities span every non-dead, non-ice, non-water biome.
        assert pool == {
            Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
            Biome.DRYLANDS, Biome.MARSH, Biome.MOUNTAIN,
            Biome.FOREST,
        }

    def test_farm_pool_is_greenlands_only(self) -> None:
        assert FEATURE_BIOMES[HexFeatureType.FARM] == (
            Biome.GREENLANDS,
        )

    def test_mansion_pool_includes_marsh(self) -> None:
        pool = set(FEATURE_BIOMES[HexFeatureType.MANSION])
        assert pool == {Biome.GREENLANDS, Biome.HILLS, Biome.MARSH}
        assert Biome.FOREST not in pool  # shrunk from prior set

    def test_cottage_pool_is_forest_only(self) -> None:
        assert FEATURE_BIOMES[HexFeatureType.COTTAGE] == (
            Biome.FOREST,
        )

    def test_temple_pool_spans_mountain_forest_sandlands_icelands(
        self,
    ) -> None:
        assert set(FEATURE_BIOMES[HexFeatureType.TEMPLE]) == {
            Biome.MOUNTAIN, Biome.FOREST,
            Biome.SANDLANDS, Biome.ICELANDS,
        }

    def test_ruin_pool_spans_five_biomes(self) -> None:
        assert set(FEATURE_BIOMES[HexFeatureType.RUIN]) == {
            Biome.FOREST, Biome.DEADLANDS,
            Biome.MARSH, Biome.SANDLANDS, Biome.ICELANDS,
        }


# ---------------------------------------------------------------------------
# Hub fallback behaviour
# ---------------------------------------------------------------------------


class TestHubFallback:
    def test_hub_falls_back_from_greenlands_to_hills_not_drylands(
        self,
    ) -> None:
        """With no greenlands, the hub must land on hills -- drylands
        is no longer a valid CITY biome (see FEATURE_BIOMES[CITY])."""
        hbb: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
        # Drylands alone is not enough: no greenlands, no hills.
        hbb[Biome.HILLS] = [HexCoord(q, 0) for q in range(4)]
        hbb[Biome.DRYLANDS] = [HexCoord(q, 1) for q in range(4)]
        rng = random.Random(0)
        hub = pick_hub(hbb, rng, cells=None)
        assert hub is not None
        # Hub must be one of the hills hexes, never drylands.
        assert hub.r == 0

    def test_hub_returns_none_without_any_city_biome(self) -> None:
        """If neither greenlands nor hills exist, no hub can be
        placed even if drylands is plentiful."""
        hbb: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
        hbb[Biome.DRYLANDS] = [HexCoord(q, 0) for q in range(5)]
        rng = random.Random(0)
        assert pick_hub(hbb, rng, cells=None) is None


# ---------------------------------------------------------------------------
# place_features: size-class pinning and community spacing
# ---------------------------------------------------------------------------


class TestPinnedSizeClass:
    def test_village_size_class_pinned_to_village(self) -> None:
        """Every VILLAGE hex now carries size_class='village' (no
        more hamlet / town roll)."""
        cells, hbb = _make_mixed_world()
        pack = _make_pack(village=(3, 3))
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        village_cells = [
            cell for cell in cells.values()
            if cell.feature is HexFeatureType.VILLAGE
        ]
        assert village_cells, "expected some VILLAGE placements"
        for cell in village_cells:
            assert cell.dungeon is not None
            assert cell.dungeon.size_class == "village"

    def test_community_size_class_pinned_to_hamlet(self) -> None:
        cells, hbb = _make_mixed_world()
        pack = _make_pack(village=(1, 1), community=(2, 2))
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        community_cells = [
            cell for cell in cells.values()
            if cell.feature is HexFeatureType.COMMUNITY
        ]
        assert community_cells, "expected COMMUNITY placements"
        for cell in community_cells:
            assert cell.dungeon is not None
            assert cell.dungeon.size_class == "hamlet"

    def test_city_size_class_pinned_to_city(self) -> None:
        cells, hbb = _make_mixed_world()
        pack = _make_pack()
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        city_cells = [
            cell for cell in cells.values()
            if cell.feature is HexFeatureType.CITY
        ]
        assert len(city_cells) == 1
        assert city_cells[0].dungeon.size_class == "city"


class TestCommunitySpacing:
    def test_community_respects_adjacent_settlement_spacing(
        self,
    ) -> None:
        """COMMUNITY hexes must not sit adjacent to another
        settlement (CITY / VILLAGE / COMMUNITY)."""
        cells, hbb = _make_mixed_world()
        pack = _make_pack(village=(2, 2), community=(2, 2))
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        settlements = {
            HexFeatureType.CITY,
            HexFeatureType.VILLAGE,
            HexFeatureType.COMMUNITY,
        }
        settlement_coords = [
            c for c, cell in cells.items()
            if cell.feature in settlements
        ]
        for c in settlement_coords:
            for n in neighbors(c):
                neighbor_cell = cells.get(n)
                if neighbor_cell is None:
                    continue
                assert neighbor_cell.feature not in settlements, (
                    f"settlement {c} is adjacent to "
                    f"{neighbor_cell.feature} at {n}"
                )


# ---------------------------------------------------------------------------
# Pack knob counts
# ---------------------------------------------------------------------------


class TestPackKnobCounts:
    def test_community_count_matches_pack_community_knob(
        self,
    ) -> None:
        cells, hbb = _make_mixed_world()
        pack = _make_pack(village=(0, 0), community=(3, 3))
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        community_count = sum(
            1 for cell in cells.values()
            if cell.feature is HexFeatureType.COMMUNITY
        )
        assert community_count == 3

    def test_ruin_count_matches_pack_ruin_knob(self) -> None:
        cells, hbb = _make_mixed_world()
        pack = _make_pack(village=(0, 0), ruin=(3, 3))
        rng = random.Random(0)
        place_features(cells, hbb, pack, rng)
        ruin_count = sum(
            1 for cell in cells.values()
            if cell.feature is HexFeatureType.RUIN
        )
        assert ruin_count == 3

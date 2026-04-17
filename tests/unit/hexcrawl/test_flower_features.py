"""Tests for feature placement in sub-hex flowers.

Milestone M6: place_flower_features() in _flowers.py.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance
from nhc.hexcrawl.model import (
    Biome,
    HexFeatureType,
    MinorFeatureType,
    SubHexCell,
    FLOWER_COORDS,
)
from nhc.hexcrawl._flowers import place_flower_features


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub_cells(biome: Biome = Biome.GREENLANDS) -> dict[HexCoord, SubHexCell]:
    return {
        c: SubHexCell(coord=c, biome=biome)
        for c in FLOWER_COORDS
    }


# ---------------------------------------------------------------------------
# Major feature placement
# ---------------------------------------------------------------------------


def test_exactly_one_major_feature() -> None:
    cells = _make_sub_cells()
    rng = random.Random(42)
    fc = place_flower_features(
        cells, major=HexFeatureType.CAVE, biome=Biome.GREENLANDS,
        rng=rng,
    )
    major_cells = [
        c for c, cell in cells.items()
        if cell.major_feature is not HexFeatureType.NONE
    ]
    assert len(major_cells) == 1
    assert major_cells[0] == fc


def test_feature_cell_in_rings_0_1_most_of_time() -> None:
    """Feature is weighted toward rings 0-1 (>65% of placements).

    With weights ring0=3, ring1=5, ring2=1 the expected
    probability is ~73% (7 weighted slots / 45 total weight).
    """
    center = HexCoord(0, 0)
    inner_count = 0
    for seed in range(200):
        cells = _make_sub_cells()
        rng = random.Random(seed)
        fc = place_flower_features(
            cells, major=HexFeatureType.VILLAGE,
            biome=Biome.GREENLANDS, rng=rng,
        )
        if distance(center, fc) <= 1:
            inner_count += 1
    assert inner_count / 200 > 0.65


def test_feature_avoids_river_sub_hexes() -> None:
    """Feature should not be placed on a sub-hex with a river."""
    center = HexCoord(0, 0)
    for seed in range(100):
        cells = _make_sub_cells()
        # Mark ring 0 and some ring 1 cells as river
        cells[HexCoord(0, 0)].has_river = True
        cells[HexCoord(0, -1)].has_river = True
        cells[HexCoord(1, -1)].has_river = True
        rng = random.Random(seed)
        fc = place_flower_features(
            cells, major=HexFeatureType.RUIN,
            biome=Biome.FOREST, rng=rng,
        )
        assert cells[fc].has_river is False, (
            f"seed {seed}: feature placed on river sub-hex {fc}"
        )


def test_no_major_feature_when_none() -> None:
    """NONE feature type places nothing."""
    cells = _make_sub_cells()
    rng = random.Random(42)
    fc = place_flower_features(
        cells, major=HexFeatureType.NONE,
        biome=Biome.GREENLANDS, rng=rng,
    )
    assert fc is None
    major_cells = [
        c for c, cell in cells.items()
        if cell.major_feature is not HexFeatureType.NONE
    ]
    assert len(major_cells) == 0


# ---------------------------------------------------------------------------
# Minor feature density
# ---------------------------------------------------------------------------


def test_minor_features_in_density_range_greenlands() -> None:
    """Greenlands: 3-6 minor features."""
    cells = _make_sub_cells(Biome.GREENLANDS)
    rng = random.Random(42)
    place_flower_features(
        cells, major=HexFeatureType.VILLAGE,
        biome=Biome.GREENLANDS, rng=rng,
    )
    count = sum(
        1 for cell in cells.values()
        if cell.minor_feature is not MinorFeatureType.NONE
    )
    assert 3 <= count <= 6, f"greenlands: got {count} minor features"


def test_minor_features_in_density_range_mountain() -> None:
    """Mountain: 1-3 minor features."""
    cells = _make_sub_cells(Biome.MOUNTAIN)
    rng = random.Random(42)
    place_flower_features(
        cells, major=HexFeatureType.CAVE,
        biome=Biome.MOUNTAIN, rng=rng,
    )
    count = sum(
        1 for cell in cells.values()
        if cell.minor_feature is not MinorFeatureType.NONE
    )
    assert 1 <= count <= 3, f"mountain: got {count} minor features"


def test_minor_features_avoid_feature_cell() -> None:
    """Minor features should not be placed on the major feature cell."""
    for seed in range(50):
        cells = _make_sub_cells()
        rng = random.Random(seed)
        fc = place_flower_features(
            cells, major=HexFeatureType.VILLAGE,
            biome=Biome.GREENLANDS, rng=rng,
        )
        if fc is not None:
            assert cells[fc].minor_feature is MinorFeatureType.NONE


def test_minor_features_avoid_river_road() -> None:
    """Minor features should not be placed on river or road sub-hexes."""
    for seed in range(50):
        cells = _make_sub_cells()
        cells[HexCoord(0, -1)].has_river = True
        cells[HexCoord(1, 0)].has_road = True
        rng = random.Random(seed)
        place_flower_features(
            cells, major=HexFeatureType.VILLAGE,
            biome=Biome.GREENLANDS, rng=rng,
        )
        for c, cell in cells.items():
            if cell.minor_feature is not MinorFeatureType.NONE:
                assert not cell.has_river, f"minor on river at {c}"
                assert not cell.has_road, f"minor on road at {c}"


# ---------------------------------------------------------------------------
# Lair placement
# ---------------------------------------------------------------------------


def test_lair_max_one_per_flower() -> None:
    """At most 1 lair-type feature per flower."""
    for seed in range(100):
        cells = _make_sub_cells(Biome.DEADLANDS)
        rng = random.Random(seed)
        place_flower_features(
            cells, major=HexFeatureType.NONE,
            biome=Biome.DEADLANDS, rng=rng,
        )
        lair_count = sum(
            1 for cell in cells.values()
            if cell.minor_feature in (
                MinorFeatureType.LAIR,
                MinorFeatureType.NEST,
                MinorFeatureType.BURROW,
            )
        )
        assert lair_count <= 1, f"seed {seed}: {lair_count} lairs"


def test_lair_has_encounter_modifier() -> None:
    """Lair sub-hexes have encounter_modifier = 3.0."""
    found_lair = False
    for seed in range(200):
        cells = _make_sub_cells(Biome.DEADLANDS)
        rng = random.Random(seed)
        place_flower_features(
            cells, major=HexFeatureType.NONE,
            biome=Biome.DEADLANDS, rng=rng,
        )
        for cell in cells.values():
            if cell.minor_feature in (
                MinorFeatureType.LAIR,
                MinorFeatureType.NEST,
                MinorFeatureType.BURROW,
            ):
                assert cell.encounter_modifier == 3.0
                found_lair = True
    assert found_lair, "expected at least one lair in 200 deadlands seeds"


def test_lair_placed_at_ring2() -> None:
    """Lairs are always placed in ring 2."""
    center = HexCoord(0, 0)
    for seed in range(200):
        cells = _make_sub_cells(Biome.DEADLANDS)
        rng = random.Random(seed)
        place_flower_features(
            cells, major=HexFeatureType.NONE,
            biome=Biome.DEADLANDS, rng=rng,
        )
        for c, cell in cells.items():
            if cell.minor_feature in (
                MinorFeatureType.LAIR,
                MinorFeatureType.NEST,
                MinorFeatureType.BURROW,
            ):
                assert distance(center, c) == 2, (
                    f"lair at {c} not ring 2"
                )


# ---------------------------------------------------------------------------
# Water biome: no features
# ---------------------------------------------------------------------------


def test_water_no_minor_features() -> None:
    cells = _make_sub_cells(Biome.WATER)
    rng = random.Random(42)
    place_flower_features(
        cells, major=HexFeatureType.NONE,
        biome=Biome.WATER, rng=rng,
    )
    for cell in cells.values():
        assert cell.minor_feature is MinorFeatureType.NONE

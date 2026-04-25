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


# ---------------------------------------------------------------------------
# M6e: macro feature derives from the flower's feature_cell
# ---------------------------------------------------------------------------


def test_macro_feature_derives_from_flower_feature_cell() -> None:
    """After M6e, ``HexCell.feature`` and ``HexCell.dungeon`` are
    properties that read from ``flower.cells[feature_cell]``. The
    flower is the source of truth; mutating the feature_cell
    sub-hex changes what the macro reports."""
    from nhc.hexcrawl.model import (
        DungeonRef, HexCell, HexFlower, SubHexCell,
    )

    parent = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.FOREST,
        feature=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement",
            site_kind="town", size_class="village",
        ),
    )
    sub_cells = {c: SubHexCell(coord=c, biome=Biome.FOREST)
                 for c in FLOWER_COORDS}
    fc = HexCoord(0, 0)
    sub_cells[fc].major_feature = HexFeatureType.CITY
    sub_cells[fc].dungeon = DungeonRef(
        template="procedural:settlement",
        site_kind="town", size_class="village",
    )
    parent.flower = HexFlower(
        parent_coord=parent.coord,
        cells=sub_cells,
        feature_cell=fc,
    )
    # Property reads derive from the feature_cell sub-hex.
    assert parent.feature is HexFeatureType.CITY
    assert parent.dungeon is sub_cells[fc].dungeon

    # Mutating the sub-cell propagates to the macro property.
    sub_cells[fc].major_feature = HexFeatureType.RUIN
    assert parent.feature is HexFeatureType.RUIN
    sub_cells[fc].dungeon = None
    assert parent.dungeon is None


def test_macro_feature_setter_propagates_to_feature_cell() -> None:
    """Writing to ``HexCell.feature`` / ``HexCell.dungeon`` after
    the flower exists propagates to the feature_cell sub-hex so
    later reads through either path agree."""
    from nhc.hexcrawl.model import (
        DungeonRef, HexCell, HexFlower, SubHexCell,
    )

    parent = HexCell(coord=HexCoord(0, 0), biome=Biome.FOREST)
    sub_cells = {c: SubHexCell(coord=c, biome=Biome.FOREST)
                 for c in FLOWER_COORDS}
    fc = HexCoord(0, 0)
    parent.flower = HexFlower(
        parent_coord=parent.coord,
        cells=sub_cells,
        feature_cell=fc,
    )
    parent.feature = HexFeatureType.KEEP
    parent.dungeon = DungeonRef(
        template="procedural:keep", site_kind="keep",
    )
    # Setter wrote through to the feature_cell sub-hex.
    assert sub_cells[fc].major_feature is HexFeatureType.KEEP
    assert sub_cells[fc].dungeon is parent.dungeon


def test_macro_feature_falls_back_when_flower_is_none() -> None:
    """A bare ``HexCell`` (no flower yet) keeps the legacy
    behaviour: setter / getter round-trip through the underlying
    private field. Lets generators that run before flower assembly
    still write features the way they always have."""
    from nhc.hexcrawl.model import DungeonRef, HexCell

    cell = HexCell(coord=HexCoord(1, 1), biome=Biome.FOREST)
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave")
    assert cell.feature is HexFeatureType.CAVE
    assert cell.dungeon is not None
    assert cell.dungeon.template == "procedural:cave"

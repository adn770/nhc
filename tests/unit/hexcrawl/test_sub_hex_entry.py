"""Tests for sub-hex entry: folding the macro feature onto the
feature_cell and sub-hex dispatch.

Companion to ``nhc_sub_hex_entry_plan.md``.
"""

from __future__ import annotations

from nhc.core.save import _deserialize_hex_world, _serialize_hex_world
from nhc.hexcrawl._flowers import generate_flower
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
    HexWorld,
)


# ---------------------------------------------------------------------------
# M1: folding macro feature + DungeonRef onto feature_cell sub-hex
# ---------------------------------------------------------------------------


def test_feature_cell_sub_hex_gets_parent_dungeon() -> None:
    """The feature_cell sub-hex carries a copy of the macro DungeonRef."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.FOREST,
        feature=HexFeatureType.CAVE,
        dungeon=DungeonRef(
            template="procedural:cave",
            depth=2,
            site_kind=None,
            size_class=None,
            faction="goblin",
        ),
        elevation=0.5,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    assert flower.feature_cell is not None
    fc = flower.cells[flower.feature_cell]
    assert fc.major_feature is HexFeatureType.CAVE
    assert fc.dungeon is not None
    assert fc.dungeon.template == "procedural:cave"
    assert fc.dungeon.depth == 2
    assert fc.dungeon.faction == "goblin"


def test_non_feature_cells_have_no_dungeon() -> None:
    """Only the feature_cell holds a dungeon; other sub-hexes do not."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement",
            depth=1,
            site_kind="town",
            size_class="city",
        ),
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    fc = flower.feature_cell
    assert fc is not None
    for coord, cell in flower.cells.items():
        if coord == fc:
            assert cell.dungeon is not None
        else:
            assert cell.dungeon is None, (
                f"sub-hex {coord} unexpectedly has a dungeon"
            )


def test_no_feature_means_no_sub_hex_dungeon() -> None:
    """A macro with no feature yields no feature_cell and no dungeon."""
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.NONE,
        dungeon=None,
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    assert flower.feature_cell is None
    assert all(c.dungeon is None for c in flower.cells.values())


def test_parent_without_dungeon_still_places_feature() -> None:
    """A macro with feature but no DungeonRef leaves sub-hex dungeon None.

    Non-enterable macros like LAKE/RIVER set ``cell.feature`` but
    leave ``cell.dungeon`` unset. The fold should copy what is
    there (a ``None``) rather than synthesise a DungeonRef.
    """
    parent = HexCell(
        coord=HexCoord(3, 2),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.LAKE,
        dungeon=None,
        elevation=0.3,
    )
    flower = generate_flower(parent, {parent.coord: parent}, seed=42)
    fc = flower.feature_cell
    assert fc is not None
    assert flower.cells[fc].major_feature is HexFeatureType.LAKE
    assert flower.cells[fc].dungeon is None


def test_sub_hex_dungeon_survives_save_roundtrip() -> None:
    """Serialise/deserialise preserves every DungeonRef field on the
    feature_cell sub-hex so the dispatcher can read it after reload."""
    hw = HexWorld(pack_id="test", seed=1, width=4, height=4)
    parent = HexCell(
        coord=HexCoord(1, 1),
        biome=Biome.GREENLANDS,
        feature=HexFeatureType.CITY,
        dungeon=DungeonRef(
            template="procedural:settlement",
            depth=1,
            site_kind="town",
            size_class="city",
            faction="human",
        ),
        elevation=0.3,
    )
    parent.flower = generate_flower(parent, {parent.coord: parent}, seed=99)
    hw.set_cell(parent)

    data = _serialize_hex_world(hw)
    hw2 = _deserialize_hex_world(data)
    cell2 = hw2.get_cell(HexCoord(1, 1))
    assert cell2 is not None
    assert cell2.flower is not None
    fc2 = cell2.flower.feature_cell
    assert fc2 is not None
    sub = cell2.flower.cells[fc2]
    assert sub.dungeon is not None
    assert sub.dungeon.template == "procedural:settlement"
    assert sub.dungeon.depth == 1
    assert sub.dungeon.site_kind == "town"
    assert sub.dungeon.size_class == "city"
    assert sub.dungeon.faction == "human"

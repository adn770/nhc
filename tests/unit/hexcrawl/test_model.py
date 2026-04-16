"""Tests for HexCell, HexWorld, and the core hexcrawl enums."""

from __future__ import annotations

import pytest

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    Faction,
    HexCell,
    HexFeatureType,
    HexWorld,
    Rumor,
    TimeOfDay,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


def test_biome_enum_complete() -> None:
    expected = {
        "greenlands", "drylands", "sandlands",
        "icelands", "deadlands", "forest", "mountain",
        # Added in M-G.1 for the noise generator + Blackmarsh
        # wetlands prep.
        "hills", "marsh", "swamp",
    }
    assert {b.value for b in Biome} == expected


def test_hexfeature_enum_complete() -> None:
    # NONE is the sentinel for hexes without a feature.
    expected = {
        "none", "village", "city", "tower", "keep",
        "cave", "ruin", "hole", "graveyard",
        "crystals", "stones", "wonder", "portal",
        "lake", "river",
    }
    assert {f.value for f in HexFeatureType} == expected


def test_timeofday_has_four_segments_in_order() -> None:
    assert [t.name for t in TimeOfDay] == [
        "MORNING", "MIDDAY", "EVENING", "NIGHT",
    ]
    assert [t.value for t in TimeOfDay] == [0, 1, 2, 3]


def test_timeofday_advance_within_day() -> None:
    new, days = TimeOfDay.MORNING.advance(2)
    assert new is TimeOfDay.EVENING
    assert days == 0


def test_timeofday_advance_wraps_to_next_day() -> None:
    new, days = TimeOfDay.NIGHT.advance(1)
    assert new is TimeOfDay.MORNING
    assert days == 1


def test_timeofday_advance_multiple_days() -> None:
    new, days = TimeOfDay.MORNING.advance(9)   # 2 full days + 1 segment
    assert new is TimeOfDay.MIDDAY
    assert days == 2


def test_timeofday_advance_rejects_negative() -> None:
    with pytest.raises(ValueError):
        TimeOfDay.MORNING.advance(-1)


# ---------------------------------------------------------------------------
# Simple dataclasses
# ---------------------------------------------------------------------------


def test_hexcell_default_feature_is_none() -> None:
    c = HexCell(coord=HexCoord(1, 2), biome=Biome.GREENLANDS)
    assert c.feature is HexFeatureType.NONE
    assert c.name_key is None
    assert c.desc_key is None
    assert c.dungeon is None


def test_hexcell_with_dungeon() -> None:
    d = DungeonRef(template="procedural:cave", depth=2)
    c = HexCell(
        coord=HexCoord(0, 0),
        biome=Biome.MOUNTAIN,
        feature=HexFeatureType.CAVE,
        name_key="content.testland.hex.cave1.name",
        dungeon=d,
    )
    assert c.dungeon is d
    assert c.feature is HexFeatureType.CAVE


def test_rumor_defaults() -> None:
    r = Rumor(id="atacyl", text_key="content.x.rumor.atacyl")
    assert r.truth is True
    assert r.reveals is None


def test_faction_basic() -> None:
    f = Faction(id="rangers", name_key="content.x.faction.rangers")
    assert f.id == "rangers"


# ---------------------------------------------------------------------------
# HexWorld
# ---------------------------------------------------------------------------


def _make_world(width: int = 4, height: int = 4) -> HexWorld:
    return HexWorld(pack_id="testland", seed=1, width=width, height=height)


def test_hexworld_init_empty() -> None:
    w = _make_world()
    assert w.pack_id == "testland"
    assert w.seed == 1
    assert w.width == 4
    assert w.height == 4
    assert w.cells == {}
    assert w.revealed == set()
    assert w.visited == set()
    assert w.cleared == set()
    assert w.looted == set()
    assert w.day == 1
    assert w.time is TimeOfDay.MORNING
    assert w.last_hub is None
    assert w.active_rumors == []
    assert w.expedition_party == []


def test_hexworld_reveal_marks_set() -> None:
    w = _make_world()
    c = HexCoord(2, 1)
    assert not w.is_revealed(c)
    w.reveal(c)
    assert w.is_revealed(c)
    assert c in w.revealed


def test_hexworld_visit_marks_revealed_and_visited() -> None:
    w = _make_world()
    c = HexCoord(3, 3)
    w.visit(c)
    assert w.is_revealed(c)
    assert c in w.visited


def test_hexworld_clear_dungeon_marks_set() -> None:
    w = _make_world()
    c = HexCoord(1, 1)
    assert not w.is_cleared(c)
    w.clear_dungeon(c)
    assert w.is_cleared(c)
    assert c in w.cleared


def test_hexworld_advance_clock_within_day() -> None:
    w = _make_world()
    w.advance_clock(1)
    assert w.day == 1
    assert w.time is TimeOfDay.MIDDAY


def test_hexworld_advance_clock_wraps_day() -> None:
    w = _make_world()
    w.advance_clock(4)
    assert w.day == 2
    assert w.time is TimeOfDay.MORNING


def test_hexworld_advance_clock_segments_multiple_days() -> None:
    w = _make_world()
    w.advance_clock(10)   # 2 days + 2 segments
    assert w.day == 3
    assert w.time is TimeOfDay.EVENING


def test_hexworld_advance_clock_rejects_negative() -> None:
    w = _make_world()
    with pytest.raises(ValueError):
        w.advance_clock(-1)


def test_hexworld_reveal_neighbors_helper() -> None:
    # reveal_with_neighbors is shape-aware: it reveals the centre
    # plus each neighbour that is a populated cell. Populate a
    # 4x4 patch and check that the helper adds neighbours only
    # where cells exist.
    w = _make_world(width=4, height=4)
    for q in range(4):
        for r in range(4):
            w.set_cell(HexCell(coord=HexCoord(q, r), biome=Biome.GREENLANDS))
    w.reveal_with_neighbors(HexCoord(1, 1))
    assert HexCoord(1, 1) in w.revealed
    assert HexCoord(0, 1) in w.revealed
    assert HexCoord(1, 0) in w.revealed
    assert HexCoord(2, 1) in w.revealed
    # Every revealed coord corresponds to a populated cell.
    for c in w.revealed:
        assert c in w.cells


def test_hexworld_set_cell_and_lookup() -> None:
    w = _make_world()
    c = HexCoord(0, 0)
    cell = HexCell(coord=c, biome=Biome.FOREST)
    w.set_cell(cell)
    assert w.get_cell(c) is cell


def test_hexworld_get_cell_missing_returns_none() -> None:
    w = _make_world()
    assert w.get_cell(HexCoord(0, 0)) is None

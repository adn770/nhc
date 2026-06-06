"""Tests for Phase 1 model extensions."""

import pickle

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.hexcrawl.model import DungeonRef


class TestTileSlots:
    """Tile is slotted for fast bulk allocation in create_empty."""

    def test_tile_has_no_dict(self):
        t = Tile(terrain=Terrain.VOID)
        assert not hasattr(t, "__dict__")

    def test_tile_rejects_unknown_attribute(self):
        t = Tile()
        import pytest
        with pytest.raises(AttributeError):
            t.not_a_field = 1  # type: ignore[attr-defined]

    def test_tile_round_trips_through_pickle(self):
        # New saves (slots pickle form) must round-trip cleanly.
        t = Tile(
            terrain=Terrain.FLOOR, feature="door_open",
            buried=["gold"], surface_type=SurfaceType.STREET,
        )
        back = pickle.loads(pickle.dumps(t))
        assert back == t
        assert back.buried == ["gold"]


class TestTileEmpty:
    """``Tile.empty()`` is the positional fast-path constructor used by
    ``create_empty`` for bulk VOID allocation. It must stay equivalent
    to the keyword form, and the slot order it relies on must not drift.
    """

    def test_empty_equals_keyword_void(self):
        assert Tile.empty() == Tile(terrain=Terrain.VOID)

    def test_empty_is_distinct_instance(self):
        # Each call must yield a fresh object — no shared flyweight, or
        # in-place mutation (buried.append, visible sweeps) would alias.
        a = Tile.empty()
        b = Tile.empty()
        assert a is not b
        assert a.buried is not b.buried

    def test_slot_order_pins_positional_constructor(self):
        # ``empty()`` constructs positionally, so a field insertion ahead
        # of ``terrain`` would silently corrupt it. Pin the expected order.
        assert Tile.__slots__ == (
            "terrain", "feature", "explored", "visible", "door_side",
            "opened_at_turn", "buried", "dug_floor", "dug_wall",
            "surface_type",
        )


class TestLevelOrigin:
    """``Level`` carries a world-space origin so building floors can
    allocate a footprint-sized grid while every coordinate stays a
    world value. Surfaces / dungeons keep origin (0, 0) and behave
    exactly as before.
    """

    def test_default_origin_is_zero(self):
        lvl = Level.create_empty("l", "L", 1, 4, 3)
        assert (lvl.origin_x, lvl.origin_y) == (0, 0)

    def test_origin_zero_tile_at_unchanged(self):
        lvl = Level.create_empty("l", "L", 1, 4, 3)
        rows = list(lvl.iter_rows())
        assert lvl.tile_at(0, 0) is rows[0][0]
        assert lvl.tile_at(3, 2) is rows[2][3]
        assert lvl.tile_at(4, 0) is None  # out of bounds

    def test_offset_grid_indexes_by_world_coord(self):
        # A 4x3 grid anchored at world (10, 20): world (10,20) maps to
        # physical [0][0], world (13,22) to physical [2][3].
        lvl = Level.create_empty(
            "f", "F", 1, 4, 3, origin_x=10, origin_y=20,
        )
        rows = list(lvl.iter_rows())
        assert lvl.tile_at(10, 20) is rows[0][0]
        assert lvl.tile_at(13, 22) is rows[2][3]

    def test_offset_grid_bounds(self):
        lvl = Level.create_empty(
            "f", "F", 1, 4, 3, origin_x=10, origin_y=20,
        )
        assert lvl.in_bounds(10, 20)
        assert lvl.in_bounds(13, 22)
        assert not lvl.in_bounds(9, 20)
        assert not lvl.in_bounds(14, 20)
        assert not lvl.in_bounds(10, 19)
        assert not lvl.in_bounds(10, 23)
        # Out-of-bounds world coords return None, never IndexError.
        assert lvl.tile_at(9, 20) is None
        assert lvl.tile_at(14, 22) is None

    def test_set_tile_replaces_through_offset(self):
        lvl = Level.create_empty(
            "f", "F", 1, 4, 3, origin_x=10, origin_y=20,
        )
        marker = Tile(terrain=Terrain.FLOOR)
        lvl.set_tile(13, 22, marker)
        assert list(lvl.iter_rows())[2][3] is marker
        assert lvl.tile_at(13, 22) is marker

    def test_iter_world_yields_world_coords(self):
        lvl = Level.create_empty(
            "f", "F", 1, 2, 2, origin_x=10, origin_y=20,
        )
        coords = {(wx, wy) for wx, wy, _ in lvl.iter_world()}
        assert coords == {(10, 20), (11, 20), (10, 21), (11, 21)}
        for wx, wy, tile in lvl.iter_world():
            assert lvl.tile_at(wx, wy) is tile

    def test_iter_local_yields_physical_indices(self):
        lvl = Level.create_empty(
            "f", "F", 1, 2, 2, origin_x=10, origin_y=20,
        )
        coords = {(lx, ly) for lx, ly, _ in lvl.iter_local()}
        assert coords == {(0, 0), (1, 0), (0, 1), (1, 1)}
        for lx, ly, tile in lvl.iter_local():
            # local (lx, ly) maps to world (lx + origin, ly + origin)
            assert lvl.tile_at(lx + 10, ly + 20) is tile

    def test_iter_tiles_covers_every_cell(self):
        lvl = Level.create_empty("l", "L", 1, 3, 2)
        assert sum(1 for _ in lvl.iter_tiles()) == 6
        marker = Tile(terrain=Terrain.FLOOR)
        lvl.set_tile(1, 1, marker)
        assert marker in list(lvl.iter_tiles())

    def test_iter_rows_yields_physical_rows(self):
        lvl = Level.create_empty(
            "f", "F", 1, 2, 3, origin_x=5, origin_y=7,
        )
        rows = list(lvl.iter_rows())
        assert len(rows) == 3 and all(len(r) == 2 for r in rows)
        assert rows[0][0] is lvl.tile_at(5, 7)
        assert rows[2][1] is lvl.tile_at(6, 9)

    def test_tiles_field_is_private(self):
        # The raw grid is ``_tiles``; ``.tiles`` must not exist so a
        # stray world-coord index can't silently read the offset array.
        lvl = Level.create_empty("l", "L", 1, 2, 2)
        assert not hasattr(lvl, "tiles")


class TestDungeonRefExtensions:
    def test_size_class_default(self):
        ref = DungeonRef(template="procedural:cave")
        assert ref.size_class is None

    def test_size_class_set(self):
        ref = DungeonRef(
            template="procedural:cave", size_class="town",
        )
        assert ref.size_class == "town"

    def test_faction_default(self):
        ref = DungeonRef(template="procedural:cave")
        assert ref.faction is None

    def test_faction_set(self):
        ref = DungeonRef(
            template="procedural:cave", faction="goblin",
        )
        assert ref.faction == "goblin"

    def test_site_kind_default_none(self):
        ref = DungeonRef(template="procedural:cave")
        assert ref.site_kind is None

    def test_site_kind_set(self):
        ref = DungeonRef(
            template="procedural:radial", site_kind="tower",
        )
        assert ref.site_kind == "tower"


class TestTileExtensions:
    def test_street_surface_default_none(self):
        tile = Tile()
        assert tile.surface_type == SurfaceType.NONE

    def test_track_surface_default_none(self):
        tile = Tile()
        assert tile.surface_type == SurfaceType.NONE

    def test_street_surface_set(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET,
        )
        assert tile.surface_type == SurfaceType.STREET

    def test_track_surface_set(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.TRACK,
        )
        assert tile.surface_type == SurfaceType.TRACK

    def test_street_tile_is_walkable(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.STREET,
        )
        assert tile.walkable is True

    def test_track_tile_is_walkable(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.TRACK,
        )
        assert tile.walkable is True


class TestSurfaceType:
    def test_has_none_value(self):
        assert SurfaceType.NONE.value == "none"

    def test_has_all_expected_values(self):
        expected = {
            "none", "corridor", "track", "street",
            "field", "garden", "palisade", "fortification",
            "paved", "brick", "flagstone", "opus_romano",
            "pavement",
        }
        actual = {s.value for s in SurfaceType}
        assert actual == expected

    def test_mutually_exclusive_lookup_by_value(self):
        assert SurfaceType("field") is SurfaceType.FIELD
        assert SurfaceType("garden") is SurfaceType.GARDEN
        assert SurfaceType("palisade") is SurfaceType.PALISADE
        assert SurfaceType("fortification") is SurfaceType.FORTIFICATION


class TestTileSurfaceType:
    def test_default_is_none(self):
        assert Tile().surface_type == SurfaceType.NONE

    def test_set_field(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.FIELD,
        )
        assert tile.surface_type == SurfaceType.FIELD

    def test_set_garden(self):
        tile = Tile(
            terrain=Terrain.FLOOR, surface_type=SurfaceType.GARDEN,
        )
        assert tile.surface_type == SurfaceType.GARDEN

    def test_set_palisade(self):
        tile = Tile(
            terrain=Terrain.WALL, surface_type=SurfaceType.PALISADE,
        )
        assert tile.surface_type == SurfaceType.PALISADE

    def test_set_fortification(self):
        tile = Tile(
            terrain=Terrain.WALL,
            surface_type=SurfaceType.FORTIFICATION,
        )
        assert tile.surface_type == SurfaceType.FORTIFICATION

    def test_surface_type_survives_tile_construction(self):
        """surface_type round-trips through the dataclass constructor."""
        tile = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.STREET,
        )
        assert tile.surface_type == SurfaceType.STREET
        other = Tile(terrain=Terrain.FLOOR)
        assert other.surface_type == SurfaceType.NONE


class TestLevelBuildingRefs:
    def test_building_id_default_none(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        assert level.building_id is None

    def test_floor_index_default_none(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        assert level.floor_index is None

    def test_building_id_set(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        level.building_id = "tower_01"
        assert level.building_id == "tower_01"

    def test_floor_index_set(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        level.floor_index = 2
        assert level.floor_index == 2


class TestLevelInteriorFloor:
    def test_interior_floor_default_stone(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        assert level.interior_floor == "stone"

    def test_interior_floor_can_be_wood(self):
        level = Level.create_empty("l1", "L1", 1, 5, 5)
        level.interior_floor = "wood"
        assert level.interior_floor == "wood"

"""Tests for Phase 1 model extensions."""

from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.hexcrawl.model import DungeonRef


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
            template="procedural:tower", site_kind="tower",
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
            "paved",
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

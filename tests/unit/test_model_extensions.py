"""Tests for Phase 1 model extensions."""

from nhc.dungeon.model import Tile, Terrain
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


class TestTileExtensions:
    def test_is_street_default_false(self):
        tile = Tile()
        assert tile.is_street is False

    def test_is_track_default_false(self):
        tile = Tile()
        assert tile.is_track is False

    def test_is_street_set(self):
        tile = Tile(terrain=Terrain.FLOOR, is_street=True)
        assert tile.is_street is True

    def test_is_track_set(self):
        tile = Tile(terrain=Terrain.FLOOR, is_track=True)
        assert tile.is_track is True

    def test_street_tile_is_walkable(self):
        tile = Tile(terrain=Terrain.FLOOR, is_street=True)
        assert tile.walkable is True

    def test_track_tile_is_walkable(self):
        tile = Tile(terrain=Terrain.FLOOR, is_track=True)
        assert tile.walkable is True

"""Tests for level serialization — ensure debug exports capture
all fields needed for diagnostics."""

from __future__ import annotations

from nhc.core.save import _serialize_level, _deserialize_level
from nhc.dungeon.generators.cellular import CaveShape
from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, Room, SurfaceType, Terrain, Tile,
)


def _make_level() -> Level:
    level = Level.create_empty(
        "test", "Test", depth=1, width=10, height=8,
    )
    # A floor tile with surface_type=CORRIDOR
    level.tiles[3][3] = Tile(
        terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
    )
    # A floor tile that's visible
    level.tiles[4][4] = Tile(
        terrain=Terrain.FLOOR, visible=True,
    )
    # A door tile with door_side
    level.tiles[5][5] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="north",
    )
    return level


class TestTileFieldSerialization:
    def test_is_corridor_roundtrip(self):
        level = _make_level()
        data = _serialize_level(level)
        # Check the serialized tile has surface_type
        serialized_tile = data["tiles"][3][3]
        assert serialized_tile.get("surface_type") == "corridor", (
            f"surface_type missing from export: {serialized_tile}"
        )
        # Deserialize and verify
        level2 = _deserialize_level(data)
        assert (
            level2.tiles[3][3].surface_type == SurfaceType.CORRIDOR
        )

    def test_visible_roundtrip(self):
        level = _make_level()
        data = _serialize_level(level)
        serialized_tile = data["tiles"][4][4]
        assert serialized_tile.get("visible") is True
        level2 = _deserialize_level(data)
        assert level2.tiles[4][4].visible is True

    def test_door_side_roundtrip(self):
        level = _make_level()
        data = _serialize_level(level)
        serialized_tile = data["tiles"][5][5]
        assert serialized_tile.get("door_side") == "north"
        level2 = _deserialize_level(data)
        assert level2.tiles[5][5].door_side == "north"

    def test_false_defaults_omitted(self):
        """Tiles with default values should not bloat the export."""
        level = _make_level()
        data = _serialize_level(level)
        # A default VOID tile should be minimal
        empty_tile = data["tiles"][0][0]
        assert "is_corridor" not in empty_tile
        assert "visible" not in empty_tile
        assert "door_side" not in empty_tile


class TestCaveShapeSerialization:
    def test_cave_tiles_in_export(self):
        level = Level.create_empty(
            "t", "T", depth=1, width=20, height=15,
        )
        cave_tiles = {(5, 5), (6, 5), (7, 5), (5, 6), (6, 6)}
        for x, y in cave_tiles:
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        shape = CaveShape(cave_tiles)
        level.rooms.append(
            Room(id="cave_1", rect=Rect(5, 5, 3, 2), shape=shape)
        )
        data = _serialize_level(level)
        room_data = data["rooms"][0]
        assert room_data["shape"] == "cave"
        assert "tiles" in room_data, (
            "Cave room export should include its tile set"
        )
        exported_tiles = set(tuple(t) for t in room_data["tiles"])
        assert exported_tiles == cave_tiles

    def test_cave_roundtrip(self):
        level = Level.create_empty(
            "t", "T", depth=1, width=20, height=15,
        )
        cave_tiles = {(5, 5), (6, 5), (7, 5), (5, 6), (6, 6)}
        for x, y in cave_tiles:
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        shape = CaveShape(cave_tiles)
        level.rooms.append(
            Room(id="cave_1", rect=Rect(5, 5, 3, 2), shape=shape)
        )
        data = _serialize_level(level)
        level2 = _deserialize_level(data)
        assert len(level2.rooms) == 1
        room2 = level2.rooms[0]
        assert isinstance(room2.shape, CaveShape)
        assert room2.floor_tiles() == cave_tiles

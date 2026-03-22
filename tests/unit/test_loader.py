"""Tests for dungeon level loader."""

from pathlib import Path

from nhc.dungeon.loader import get_player_start, load_level
from nhc.dungeon.model import Terrain


LEVEL_PATH = Path(__file__).parent.parent.parent / "levels" / "test_level.yaml"


class TestLoadLevel:
    def test_loads_basic_metadata(self):
        level = load_level(LEVEL_PATH)
        assert level.id == "test_level"
        assert level.name == "The Sunken Cellar"
        assert level.depth == 1
        assert level.width == 40
        assert level.height == 15

    def test_tile_grid_dimensions(self):
        level = load_level(LEVEL_PATH)
        assert len(level.tiles) == level.height
        assert all(len(row) == level.width for row in level.tiles)

    def test_walls_parsed(self):
        level = load_level(LEVEL_PATH)
        # Top-left corner is a wall (box-drawing ┌)
        assert level.tile_at(0, 0).terrain == Terrain.WALL
        # Top border of entry room (x=0-7) is walls
        for x in range(8):
            assert level.tile_at(x, 0).terrain == Terrain.WALL

    def test_floor_parsed(self):
        level = load_level(LEVEL_PATH)
        # Inside the entry room (x=1..6, y=1..5)
        tile = level.tile_at(1, 1)
        assert tile.terrain == Terrain.FLOOR
        assert tile.walkable

    def test_door_parsed_as_feature(self):
        level = load_level(LEVEL_PATH)
        # Door between entry room and corridor at (7, 3)
        tile = level.tile_at(7, 3)
        assert tile.terrain == Terrain.FLOOR
        assert tile.feature == "door_closed"

    def test_stairs_parsed_as_feature(self):
        level = load_level(LEVEL_PATH)
        # Stairs up in entry room at (2, 3)
        tile = level.tile_at(2, 3)
        assert tile.terrain == Terrain.FLOOR
        assert tile.feature == "stairs_up"

        # Stairs down in exit chamber at (35, 4)
        tile = level.tile_at(35, 4)
        assert tile.terrain == Terrain.FLOOR
        assert tile.feature == "stairs_down"

    def test_water_parsed(self):
        level = load_level(LEVEL_PATH)
        # Cistern water at (23, 11)
        tile = level.tile_at(23, 11)
        assert tile.terrain == Terrain.WATER
        assert tile.walkable

    def test_void_for_empty_space(self):
        level = load_level(LEVEL_PATH)
        # Open space between rooms
        tile = level.tile_at(10, 1)
        assert tile.terrain == Terrain.VOID
        assert not tile.walkable

    def test_corridor_parsed(self):
        level = load_level(LEVEL_PATH)
        # Corridor at y=3, x=8-19 (marked '#' in map)
        tile = level.tile_at(12, 3)
        assert tile.terrain == Terrain.FLOOR
        assert tile.is_corridor
        assert tile.walkable

    def test_room_floor_not_corridor(self):
        level = load_level(LEVEL_PATH)
        # Room floor inside entry room should not be a corridor
        tile = level.tile_at(3, 2)
        assert tile.terrain == Terrain.FLOOR
        assert not tile.is_corridor

    def test_rooms_loaded(self):
        level = load_level(LEVEL_PATH)
        assert len(level.rooms) == 5
        room_ids = {r.id for r in level.rooms}
        assert room_ids == {
            "entry", "guard_room",
            "exit_chamber", "cistern", "armory",
        }

    def test_room_tags(self):
        level = load_level(LEVEL_PATH)
        entry = next(r for r in level.rooms if r.id == "entry")
        assert "entry" in entry.tags
        assert "safe" in entry.tags

    def test_room_rect(self):
        level = load_level(LEVEL_PATH)
        entry = next(r for r in level.rooms if r.id == "entry")
        assert entry.rect.x == 1
        assert entry.rect.y == 1
        assert entry.rect.width == 6
        assert entry.rect.height == 5

    def test_room_connections(self):
        level = load_level(LEVEL_PATH)
        guard = next(r for r in level.rooms if r.id == "guard_room")
        assert "corridor_main" in guard.connections
        assert "exit_chamber" in guard.connections

    def test_corridors_loaded(self):
        level = load_level(LEVEL_PATH)
        assert len(level.corridors) == 4
        main = next(c for c in level.corridors if c.id == "corridor_main")
        assert main.connects == ["entry", "guard_room"]

    def test_entities_loaded(self):
        level = load_level(LEVEL_PATH)
        assert len(level.entities) == 6

        creatures = [e for e in level.entities if e.entity_type == "creature"]
        items = [e for e in level.entities if e.entity_type == "item"]
        features = [e for e in level.entities if e.entity_type == "feature"]

        assert len(creatures) == 3
        assert len(items) == 2
        assert len(features) == 1

    def test_entity_positions(self):
        level = load_level(LEVEL_PATH)
        skeleton = next(
            e for e in level.entities
            if e.entity_id == "skeleton" and e.x == 24
        )
        assert skeleton.y == 2

    def test_entity_extra_data(self):
        level = load_level(LEVEL_PATH)
        trap = next(
            e for e in level.entities if e.entity_id == "trap_pit"
        )
        assert trap.extra["hidden"] is True
        assert trap.extra["dc"] == 12

    def test_metadata(self):
        level = load_level(LEVEL_PATH)
        assert level.metadata.theme == "crypt"
        assert level.metadata.difficulty == 1
        assert level.metadata.faction == "undead"
        assert len(level.metadata.narrative_hooks) == 2
        assert "claw marks" in level.metadata.narrative_hooks[0].lower()

    def test_ambient(self):
        level = load_level(LEVEL_PATH)
        assert "damp" in level.metadata.ambient.lower()


class TestPlayerStart:
    def test_reads_player_start(self):
        x, y = get_player_start(LEVEL_PATH)
        assert x == 2
        assert y == 3

    def test_player_start_is_on_floor(self):
        level = load_level(LEVEL_PATH)
        x, y = get_player_start(LEVEL_PATH)
        tile = level.tile_at(x, y)
        assert tile.walkable


class TestLevelConsistency:
    """Cross-check level data for internal consistency."""

    def test_all_entity_positions_are_walkable(self):
        level = load_level(LEVEL_PATH)
        for entity in level.entities:
            tile = level.tile_at(entity.x, entity.y)
            assert tile is not None, (
                f"{entity.entity_id} at ({entity.x}, {entity.y}) "
                "is out of bounds"
            )
            assert tile.walkable, (
                f"{entity.entity_id} at ({entity.x}, {entity.y}) "
                f"is on non-walkable terrain: {tile.terrain}"
            )

    def test_all_entity_positions_in_bounds(self):
        level = load_level(LEVEL_PATH)
        for entity in level.entities:
            assert level.in_bounds(entity.x, entity.y), (
                f"{entity.entity_id} at ({entity.x}, {entity.y}) "
                "is out of bounds"
            )

    def test_stairs_exist_in_map(self):
        level = load_level(LEVEL_PATH)
        stairs_up = False
        stairs_down = False
        for row in level.tiles:
            for tile in row:
                if tile.feature == "stairs_up":
                    stairs_up = True
                if tile.feature == "stairs_down":
                    stairs_down = True
        assert stairs_up, "Level must have stairs up"
        assert stairs_down, "Level must have stairs down"

    def test_rooms_within_bounds(self):
        level = load_level(LEVEL_PATH)
        for room in level.rooms:
            r = room.rect
            assert level.in_bounds(r.x, r.y), (
                f"Room {room.id} top-left out of bounds"
            )
            assert level.in_bounds(r.x2 - 1, r.y2 - 1), (
                f"Room {room.id} bottom-right out of bounds"
            )

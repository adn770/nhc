"""Tests for room shape abstraction."""

from nhc.dungeon.model import CircleShape, Rect, Room, RoomShape, RectShape


class TestRectShape:
    def test_floor_tiles_covers_full_rect(self):
        rect = Rect(2, 3, 4, 5)
        shape = RectShape()
        tiles = shape.floor_tiles(rect)
        expected = {
            (x, y)
            for y in range(3, 8)
            for x in range(2, 6)
        }
        assert tiles == expected

    def test_floor_tiles_count(self):
        rect = Rect(0, 0, 6, 4)
        shape = RectShape()
        assert len(shape.floor_tiles(rect)) == 24

    def test_floor_tiles_min_room(self):
        rect = Rect(5, 5, 4, 4)
        shape = RectShape()
        tiles = shape.floor_tiles(rect)
        assert len(tiles) == 16

    def test_perimeter_tiles_are_edges(self):
        rect = Rect(0, 0, 4, 4)
        shape = RectShape()
        perimeter = shape.perimeter_tiles(rect)
        floor = shape.floor_tiles(rect)
        # Perimeter should be a subset of floor
        assert perimeter <= floor
        # Interior (2,2 area) should not be in perimeter
        # For a 4x4 rect, interior is (1,1), (2,1), (1,2), (2,2)
        interior = floor - perimeter
        assert len(interior) == 4
        for x, y in interior:
            assert 1 <= x <= 2
            assert 1 <= y <= 2

    def test_perimeter_tiles_small_rect(self):
        """A 2x2 rect has all tiles on the perimeter."""
        rect = Rect(0, 0, 2, 2)
        shape = RectShape()
        perimeter = shape.perimeter_tiles(rect)
        assert perimeter == shape.floor_tiles(rect)


class TestRoomShapeInterface:
    def test_rect_shape_type_name(self):
        assert RectShape.type_name == "rect"

    def test_room_default_shape_is_rect(self):
        room = Room(id="r1", rect=Rect(0, 0, 5, 5))
        assert isinstance(room.shape, RectShape)

    def test_room_floor_tiles_delegates_to_shape(self):
        rect = Rect(1, 1, 3, 3)
        room = Room(id="r1", rect=rect)
        assert room.floor_tiles() == room.shape.floor_tiles(rect)

    def test_room_with_explicit_shape(self):
        shape = RectShape()
        room = Room(id="r1", rect=Rect(0, 0, 4, 4), shape=shape)
        assert room.shape is shape

    def test_shape_is_abstract(self):
        """RoomShape cannot be instantiated directly."""
        import pytest
        with pytest.raises(TypeError):
            RoomShape()


class TestCircleShape:
    def test_type_name(self):
        assert CircleShape.type_name == "circle"

    def test_5x5_circle(self):
        """5x5 is the minimum size that looks circular."""
        rect = Rect(0, 0, 5, 5)
        shape = CircleShape()
        tiles = shape.floor_tiles(rect)
        # Center (2,2) must be included
        assert (2, 2) in tiles
        # Corners should be excluded
        assert (0, 0) not in tiles
        assert (4, 0) not in tiles
        assert (0, 4) not in tiles
        assert (4, 4) not in tiles

    def test_5x5_circle_tile_count(self):
        rect = Rect(0, 0, 5, 5)
        tiles = CircleShape().floor_tiles(rect)
        # pi * r^2 = pi * 4 ≈ 12.6, discrete rasterization gives 13
        assert len(tiles) == 13

    def test_7x7_circle_symmetry(self):
        """Circle should be symmetric around its center."""
        rect = Rect(0, 0, 7, 7)
        tiles = CircleShape().floor_tiles(rect)
        cx, cy = 3, 3
        for x, y in tiles:
            # Reflect around center — all 4 quadrants
            assert (2 * cx - x, y) in tiles, f"H-mirror of ({x},{y})"
            assert (x, 2 * cy - y) in tiles, f"V-mirror of ({x},{y})"
            assert (2 * cx - x, 2 * cy - y) in tiles, f"Both of ({x},{y})"

    def test_9x9_circle(self):
        rect = Rect(5, 5, 9, 9)
        tiles = CircleShape().floor_tiles(rect)
        # Center must be floor
        assert (9, 9) in tiles
        # All tiles must be within bounding rect
        for x, y in tiles:
            assert 5 <= x < 14
            assert 5 <= y < 14

    def test_circle_fewer_tiles_than_rect(self):
        """Circle should have fewer floor tiles than a same-sized rect."""
        rect = Rect(0, 0, 7, 7)
        circle_tiles = CircleShape().floor_tiles(rect)
        rect_tiles = RectShape().floor_tiles(rect)
        assert len(circle_tiles) < len(rect_tiles)

    def test_circle_subset_of_rect(self):
        """All circle tiles must be within the bounding rect."""
        rect = Rect(3, 7, 8, 6)
        circle_tiles = CircleShape().floor_tiles(rect)
        rect_tiles = RectShape().floor_tiles(rect)
        assert circle_tiles <= rect_tiles

    def test_elliptical_non_square(self):
        """Non-square rect produces an ellipse, not a circle."""
        rect = Rect(0, 0, 9, 5)
        tiles = CircleShape().floor_tiles(rect)
        # Wider than tall — should have floor tiles at far x
        assert (1, 2) in tiles  # near left edge at center y
        assert (7, 2) in tiles  # near right edge at center y
        # But not at extreme y corners
        assert (0, 0) not in tiles
        assert (8, 0) not in tiles

    def test_tiny_rect_produces_empty(self):
        """1x1 and 2x2 rects produce empty or near-empty circles."""
        assert len(CircleShape().floor_tiles(Rect(0, 0, 1, 1))) <= 1

    def test_circle_perimeter(self):
        """Perimeter tiles should form the outer ring."""
        rect = Rect(0, 0, 7, 7)
        shape = CircleShape()
        floor = shape.floor_tiles(rect)
        perimeter = shape.perimeter_tiles(rect)
        interior = floor - perimeter
        assert len(perimeter) > 0
        assert len(interior) > 0
        assert perimeter <= floor

    def test_room_with_circle_shape(self):
        room = Room(id="r1", rect=Rect(0, 0, 7, 7), shape=CircleShape())
        tiles = room.floor_tiles()
        assert (3, 3) in tiles
        assert (0, 0) not in tiles


class TestShapeRegistry:
    def test_resolve_rect(self):
        from nhc.dungeon.model import shape_from_type
        shape = shape_from_type("rect")
        assert isinstance(shape, RectShape)

    def test_resolve_circle(self):
        from nhc.dungeon.model import shape_from_type
        shape = shape_from_type("circle")
        assert isinstance(shape, CircleShape)

    def test_resolve_unknown_defaults_to_rect(self):
        from nhc.dungeon.model import shape_from_type
        shape = shape_from_type("unknown_future_shape")
        assert isinstance(shape, RectShape)

    def test_resolve_none_defaults_to_rect(self):
        from nhc.dungeon.model import shape_from_type
        shape = shape_from_type(None)
        assert isinstance(shape, RectShape)


class TestShapeSaveLoad:
    def test_room_shape_survives_save_load(self, tmp_path):
        """Shape type is preserved through JSON save/load."""
        from nhc.core.ecs import World
        from nhc.core.save import save_game, load_game
        from nhc.dungeon.model import Level, Terrain, Tile
        from nhc.entities.components import (
            Health, Player, Position, Renderable, Stats,
        )

        tiles = [
            [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
            for _ in range(10)
        ]
        level = Level(
            id="test", name="Test", depth=1,
            width=10, height=10, tiles=tiles,
            rooms=[Room(id="room_1", rect=Rect(1, 1, 5, 5))],
        )

        world = World()
        pid = world.create_entity({
            "Position": Position(x=3, y=3, level_id="test"),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded_level, _, _, _ = load_game(save_path=path)

        assert len(loaded_level.rooms) == 1
        room = loaded_level.rooms[0]
        assert isinstance(room.shape, RectShape)
        assert room.shape.type_name == "rect"

    def test_circle_shape_survives_save_load(self, tmp_path):
        """Circle shape type is preserved through JSON save/load."""
        from nhc.core.ecs import World
        from nhc.core.save import save_game, load_game
        from nhc.dungeon.model import Level, Terrain, Tile
        from nhc.entities.components import (
            Health, Player, Position, Renderable, Stats,
        )

        tiles = [
            [Tile(terrain=Terrain.FLOOR) for _ in range(10)]
            for _ in range(10)
        ]
        level = Level(
            id="test", name="Test", depth=1,
            width=10, height=10, tiles=tiles,
            rooms=[Room(
                id="room_1", rect=Rect(1, 1, 7, 7),
                shape=CircleShape(),
            )],
        )

        world = World()
        pid = world.create_entity({
            "Position": Position(x=3, y=3, level_id="test"),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded_level, _, _, _ = load_game(save_path=path)

        room = loaded_level.rooms[0]
        assert isinstance(room.shape, CircleShape)
        assert room.shape.type_name == "circle"

class TestCircleRoomGeneration:
    """Integration tests: generate dungeons with circular rooms."""

    def _generate_with_circles(self, seed=42):
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.generators.bsp import BSPGenerator
        from nhc.utils.rng import set_seed
        set_seed(seed)
        gen = BSPGenerator()
        params = GenerationParams(
            width=60, height=40, shape_variety=1.0,
        )
        return gen.generate(params)

    def test_generates_with_circles(self):
        level = self._generate_with_circles()
        assert level is not None
        assert len(level.rooms) >= 3

    def test_has_circular_rooms(self):
        level = self._generate_with_circles()
        circle_rooms = [
            r for r in level.rooms
            if isinstance(r.shape, CircleShape)
        ]
        assert len(circle_rooms) >= 1

    def test_all_rooms_reachable(self):
        """Every room center must be reachable via flood fill."""
        from nhc.dungeon.model import Terrain
        level = self._generate_with_circles()
        # Find stairs_up as starting point
        start = None
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "stairs_up":
                    start = (x, y)
                    break
            if start:
                break
        assert start is not None

        # Flood fill
        visited = set()
        stack = [start]
        while stack:
            fx, fy = stack.pop()
            if (fx, fy) in visited:
                continue
            t = level.tile_at(fx, fy)
            if not t or t.terrain != Terrain.FLOOR:
                continue
            visited.add((fx, fy))
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                stack.append((fx + dx, fy + dy))

        # Every room center must be reachable
        for room in level.rooms:
            cx, cy = room.rect.center
            assert (cx, cy) in visited, (
                f"{room.id} center ({cx},{cy}) not reachable"
            )

    def test_has_doors(self):
        level = self._generate_with_circles()
        door_count = sum(
            1 for row in level.tiles for t in row
            if t.feature and "door" in t.feature
        )
        assert door_count >= 2

    def test_has_stairs(self):
        level = self._generate_with_circles()
        features = {
            t.feature for row in level.tiles for t in row if t.feature
        }
        assert "stairs_up" in features
        assert "stairs_down" in features

    def test_walls_surround_circle_rooms(self):
        """Circle rooms must have WALL tiles around their perimeter."""
        from nhc.dungeon.model import Terrain
        level = self._generate_with_circles()
        for room in level.rooms:
            if not isinstance(room.shape, CircleShape):
                continue
            floor = room.floor_tiles()
            for fx, fy in floor:
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = fx + dx, fy + dy
                    if (nx, ny) not in floor:
                        t = level.tile_at(nx, ny)
                        if t:
                            # Should be wall, door, or corridor
                            assert t.terrain in (
                                Terrain.WALL, Terrain.FLOOR,
                            ), (
                                f"Tile ({nx},{ny}) adjacent to "
                                f"{room.id} circle floor is "
                                f"{t.terrain}, expected WALL/FLOOR"
                            )

    def test_multiple_seeds_with_circles(self):
        """Generation with circles works across different seeds."""
        for seed in [1, 42, 99, 12345, 99999]:
            level = self._generate_with_circles(seed=seed)
            assert len(level.rooms) >= 3, f"seed={seed}"

    def test_circle_save_load_roundtrip(self, tmp_path):
        """Circles survive save→load with correct shape type."""
        from nhc.core.ecs import World
        from nhc.core.save import save_game, load_game
        from nhc.entities.components import (
            Health, Player, Position, Renderable, Stats,
        )
        level = self._generate_with_circles()
        world = World()
        cx, cy = level.rooms[0].rect.center
        pid = world.create_entity({
            "Position": Position(x=cx, y=cy, level_id=level.id),
            "Stats": Stats(strength=2, dexterity=2),
            "Health": Health(current=8, maximum=8),
            "Player": Player(),
            "Renderable": Renderable(glyph="@", color="white"),
        })

        path = tmp_path / "save.json"
        save_game(world, level, pid, 1, [], save_path=path)
        _, loaded, _, _, _ = load_game(save_path=path)

        original_circles = sum(
            1 for r in level.rooms
            if isinstance(r.shape, CircleShape)
        )
        loaded_circles = sum(
            1 for r in loaded.rooms
            if isinstance(r.shape, CircleShape)
        )
        assert loaded_circles == original_circles


class TestShapeSaveLoadBackcompat:
    """Backward compatibility for saves without shape field."""

    def test_old_save_without_shape_loads_rect(self, tmp_path):
        """Saves from before the shape field default to RectShape."""
        import json

        data = {
            "version": 1, "turn": 1, "player_id": 1, "next_id": 2,
            "entities": {
                "1": {
                    "Position": {"x": 3, "y": 3, "level_id": "test"},
                    "Player": True,
                }
            },
            "level": {
                "id": "test", "name": "Test", "depth": 1,
                "width": 5, "height": 5,
                "tiles": [
                    [{"terrain": "FLOOR"} for _ in range(5)]
                    for _ in range(5)
                ],
                "rooms": [{
                    "id": "room_1",
                    "rect": {"x": 0, "y": 0, "width": 5, "height": 5},
                    "tags": [], "description": "", "connections": [],
                    # No "shape" key — old format
                }],
                "corridors": [],
                "metadata": {},
            },
            "messages": [],
        }

        path = tmp_path / "old_save.json"
        path.write_text(json.dumps(data))

        from nhc.core.save import load_game
        _, loaded_level, _, _, _ = load_game(save_path=path)

        room = loaded_level.rooms[0]
        assert isinstance(room.shape, RectShape)

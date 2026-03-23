"""Tests for the classic dungeon generator."""

import pytest

from nhc.dungeon.classic import ClassicGenerator
from nhc.dungeon.generator import GenerationParams, Range
from nhc.dungeon.model import Terrain
from nhc.dungeon.populator import populate_level
from nhc.utils.rng import set_seed


class TestClassicGenerator:
    def test_generates_level_with_rooms(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(
            width=60, height=40,
            room_count=Range(4, 8),
            room_size=Range(4, 10),
        )
        level = gen.generate(params)

        assert level.width == 60
        assert level.height == 40
        assert len(level.rooms) >= 4

    def test_rooms_have_floor_tiles(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        for room in level.rooms:
            rect = room.rect
            cx, cy = rect.center
            tile = level.tile_at(cx, cy)
            assert tile is not None
            assert tile.terrain == Terrain.FLOOR

    def test_corridors_connect_rooms(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        assert len(level.corridors) == len(level.rooms) - 1
        for corridor in level.corridors:
            assert len(corridor.connects) == 2

    def test_stairs_placed(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        # First room should have stairs_up
        first_cx, first_cy = level.rooms[0].rect.center
        assert level.tiles[first_cy][first_cx].feature == "stairs_up"

        # Last room should have stairs_down
        last_cx, last_cy = level.rooms[-1].rect.center
        assert level.tiles[last_cy][last_cx].feature == "stairs_down"

    def test_border_is_walls(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=40, height=30)
        level = gen.generate(params)

        for x in range(level.width):
            assert level.tiles[0][x].terrain == Terrain.WALL
            assert level.tiles[level.height - 1][x].terrain == Terrain.WALL
        for y in range(level.height):
            assert level.tiles[y][0].terrain == Terrain.WALL
            assert level.tiles[y][level.width - 1].terrain == Terrain.WALL

    def test_deterministic_with_seed(self):
        """Same seed produces identical layouts."""
        gen = ClassicGenerator()
        params = GenerationParams(width=50, height=30)

        set_seed(123)
        level1 = gen.generate(params)

        set_seed(123)
        level2 = gen.generate(params)

        assert len(level1.rooms) == len(level2.rooms)
        for r1, r2 in zip(level1.rooms, level2.rooms):
            assert r1.rect.x == r2.rect.x
            assert r1.rect.y == r2.rect.y


class TestPopulator:
    def test_populates_entities(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level, creature_count=3, item_count=2, trap_count=1)

        creatures = [
            e for e in level.entities if e.entity_type == "creature"
        ]
        items = [e for e in level.entities if e.entity_type == "item"]
        features = [e for e in level.entities if e.entity_type == "feature"]

        assert len(creatures) <= 3
        # items includes gold piles placed by the populator
        assert len(items) >= 1
        assert len(features) <= 1
        assert len(level.entities) > 0

    def test_entities_on_floor_tiles(self):
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level)

        for entity in level.entities:
            tile = level.tile_at(entity.x, entity.y)
            assert tile is not None
            assert tile.terrain == Terrain.FLOOR

    def test_no_entities_in_first_room(self):
        """Entities should not be placed in the player spawn room."""
        set_seed(42)
        gen = ClassicGenerator()
        params = GenerationParams(width=60, height=40)
        level = gen.generate(params)

        populate_level(level, creature_count=5, item_count=5)

        if level.rooms:
            spawn_rect = level.rooms[0].rect
            for entity in level.entities:
                in_spawn = (
                    spawn_rect.x <= entity.x < spawn_rect.x2
                    and spawn_rect.y <= entity.y < spawn_rect.y2
                )
                assert not in_spawn, (
                    f"{entity.entity_id} placed in spawn room"
                )

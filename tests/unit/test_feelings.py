"""Tests for level feelings and Terrain.GRASS."""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.dungeon.terrain import apply_terrain


def _make_level(
    depth: int = 2, theme: str = "dungeon",
    width: int = 20, height: int = 20,
) -> Level:
    """Create a test level with all-floor interior."""
    tiles = [[Tile(terrain=Terrain.VOID) for _ in range(width)]
             for _ in range(height)]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level = Level(
        id="test", name="Test", depth=depth,
        width=width, height=height, tiles=tiles,
        rooms=[Room(id="r1", rect=Rect(1, 1, width - 2, height - 2),
                    tags=["entry"])],
    )
    level.metadata = LevelMetadata(theme=theme)
    return level


def _count_terrain(level: Level, terrain: Terrain) -> int:
    return sum(
        1 for row in level.tiles for t in row
        if t.terrain == terrain
    )


class TestGrassTerrain:
    """Terrain.GRASS basic properties."""

    def test_grass_tile_is_walkable(self):
        tile = Tile(terrain=Terrain.GRASS)
        assert tile.walkable

    def test_grass_tile_does_not_block_sight(self):
        tile = Tile(terrain=Terrain.GRASS)
        assert not tile.blocks_sight


class TestOvergrownFeeling:
    """Overgrown feeling places GRASS tiles."""

    def test_overgrown_places_grass(self):
        level = _make_level(theme="forest")  # high grass_seed
        # Force overgrown feeling: use an rng that rolls < 0.10
        # then picks "overgrown" from FEELINGS
        rng = random.Random(1)
        # Monkey-patch to force the feeling
        original_random = rng.random
        original_choice = rng.choice
        call_count = [0]

        def forced_random():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.01  # < 0.10, triggers feeling roll
            return original_random()

        def forced_choice(seq):
            if seq == ["normal", "flooded", "overgrown", "barren"]:
                return "overgrown"
            return original_choice(seq)

        rng.random = forced_random
        rng.choice = forced_choice

        apply_terrain(level, rng)

        grass_count = _count_terrain(level, Terrain.GRASS)
        assert grass_count > 0
        assert level.metadata.feeling == "overgrown"

    def test_normal_theme_also_produces_grass(self):
        """Even without overgrown, themes with grass_seed > 0 grow grass."""
        level = _make_level(depth=1, theme="forest")  # depth 1 = no feeling
        rng = random.Random(42)
        apply_terrain(level, rng)
        grass_count = _count_terrain(level, Terrain.GRASS)
        assert grass_count > 0


class TestFloodedFeeling:
    """Flooded feeling increases water tiles."""

    def test_flooded_has_water(self):
        level_normal = _make_level(depth=1, theme="dungeon")
        rng_normal = random.Random(100)
        apply_terrain(level_normal, rng_normal)
        water_normal = _count_terrain(level_normal, Terrain.WATER)

        level_flooded = _make_level(theme="dungeon")
        rng = random.Random(1)
        original_random = rng.random
        call_count = [0]

        def forced_random():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.01
            return original_random()

        rng.random = forced_random
        rng.choice = lambda seq: "flooded"

        apply_terrain(level_flooded, rng)
        water_flooded = _count_terrain(level_flooded, Terrain.WATER)
        assert water_flooded > 0


class TestBarrenFeeling:
    """Barren feeling places no terrain features."""

    def test_barren_no_terrain(self):
        level = _make_level(theme="forest")
        rng = random.Random(1)
        original_random = rng.random
        call_count = [0]

        def forced_random():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.01
            return original_random()

        rng.random = forced_random
        rng.choice = lambda seq: "barren"

        apply_terrain(level, rng)
        assert _count_terrain(level, Terrain.WATER) == 0
        assert _count_terrain(level, Terrain.GRASS) == 0


class TestFeelingMetadata:
    """Feeling is stored on level metadata."""

    def test_feeling_stored_normal(self):
        level = _make_level(depth=1)  # depth 1 never rolls feeling
        rng = random.Random(42)
        apply_terrain(level, rng)
        assert level.metadata.feeling == "normal"

    def test_feeling_stored_barren(self):
        level = _make_level(theme="dungeon")
        rng = random.Random(1)
        original_random = rng.random
        call_count = [0]

        def forced_random():
            call_count[0] += 1
            if call_count[0] == 1:
                return 0.01
            return original_random()

        rng.random = forced_random
        rng.choice = lambda seq: "barren"

        apply_terrain(level, rng)
        assert level.metadata.feeling == "barren"


class TestGrassNotOnCorridors:
    """Grass should not appear on corridor tiles."""

    def test_corridors_stay_clear(self):
        level = _make_level(depth=1, theme="forest")
        # Mark some tiles as corridors
        for x in range(1, 10):
            level.tiles[5][x].surface_type = SurfaceType.CORRIDOR
        rng = random.Random(42)
        apply_terrain(level, rng)
        for x in range(1, 10):
            assert level.tiles[5][x].terrain != Terrain.GRASS

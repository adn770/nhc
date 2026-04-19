"""Tests for post-generation transforms."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, Terrain
from nhc.dungeon.transforms import (
    TRANSFORM_REGISTRY,
    add_cart_tracks,
    add_ore_deposits,
    narrow_corridors,
)


def _make_level(seed: int = 42) -> Level:
    """Generate a simple BSP level for transform testing."""
    rng = random.Random(seed)
    gen = BSPGenerator()
    return gen.generate(GenerationParams(
        width=80, height=40, depth=1, seed=seed,
    ), rng=rng)


class TestTransformRegistry:
    def test_all_transforms_registered(self):
        assert "add_cart_tracks" in TRANSFORM_REGISTRY
        assert "add_ore_deposits" in TRANSFORM_REGISTRY
        assert "narrow_corridors" in TRANSFORM_REGISTRY


class TestAddCartTracks:
    def test_marks_corridor_tiles_as_tracks(self):
        level = _make_level()
        rng = random.Random(42)
        add_cart_tracks(level, rng)
        track_tiles = sum(
            1 for row in level.tiles for t in row if t.is_track
        )
        assert track_tiles > 0

    def test_tracks_only_on_corridors(self):
        level = _make_level()
        rng = random.Random(42)
        add_cart_tracks(level, rng)
        for row in level.tiles:
            for t in row:
                if t.is_track:
                    assert t.is_corridor, (
                        "Track tile must be a corridor tile"
                    )


class TestAddOreDeposits:
    def test_places_ore_on_walls(self):
        level = _make_level()
        rng = random.Random(42)
        add_ore_deposits(level, rng)
        ore_count = sum(
            1 for row in level.tiles for t in row
            if t.feature == "ore_deposit"
        )
        assert ore_count > 0

    def test_ore_only_on_wall_terrain(self):
        level = _make_level()
        rng = random.Random(42)
        add_ore_deposits(level, rng)
        for row in level.tiles:
            for t in row:
                if t.feature == "ore_deposit":
                    assert t.terrain == Terrain.WALL


class TestNarrowCorridors:
    def test_reduces_corridor_width(self):
        level = _make_level()
        corridors_before = sum(
            1 for row in level.tiles for t in row
            if t.is_corridor and t.terrain == Terrain.FLOOR
        )
        rng = random.Random(42)
        narrow_corridors(level, rng)
        corridors_after = sum(
            1 for row in level.tiles for t in row
            if t.is_corridor and t.terrain == Terrain.FLOOR
        )
        # Should have same or fewer corridor tiles
        assert corridors_after <= corridors_before

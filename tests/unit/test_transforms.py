"""Tests for post-generation transforms."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, SurfaceType, Terrain
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
            1 for row in level.tiles for t in row
            if t.surface_type == SurfaceType.TRACK
        )
        assert track_tiles > 0

    def test_tracks_only_on_corridors(self):
        level = _make_level()
        rng = random.Random(42)
        # Capture corridor tiles BEFORE the transform flips them to
        # TRACK -- add_cart_tracks replaces CORRIDOR with TRACK on
        # the same tile, so post-transform we can only check that
        # track tiles originated from corridor tiles.
        pre_corridors = {
            (x, y)
            for y, row in enumerate(level.tiles)
            for x, t in enumerate(row)
            if t.surface_type == SurfaceType.CORRIDOR
        }
        add_cart_tracks(level, rng)
        for y, row in enumerate(level.tiles):
            for x, t in enumerate(row):
                if t.surface_type == SurfaceType.TRACK:
                    assert (x, y) in pre_corridors, (
                        "Track tile must originate from a corridor"
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
            if t.surface_type == SurfaceType.CORRIDOR
            and t.terrain == Terrain.FLOOR
        )
        rng = random.Random(42)
        narrow_corridors(level, rng)
        corridors_after = sum(
            1 for row in level.tiles for t in row
            if t.surface_type == SurfaceType.CORRIDOR
            and t.terrain == Terrain.FLOOR
        )
        # Should have same or fewer corridor tiles
        assert corridors_after <= corridors_before

"""Tests for post-generation transforms."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
from nhc.dungeon.transforms import (
    MIN_TRACK_RUN_LENGTH,
    TRANSFORM_REGISTRY,
    add_cart_tracks,
    add_ore_deposits,
    narrow_corridors,
)


def _empty_level(w: int, h: int) -> Level:
    """Build a void Level for hand-crafted track-stub fixtures."""
    return Level.create_empty("t", "t", 0, w, h)


def _stamp_corridor_run(
    level: Level, points: list[tuple[int, int]],
) -> None:
    for x, y in points:
        level.tiles[y][x] = Tile(
            terrain=Terrain.FLOOR,
            surface_type=SurfaceType.CORRIDOR,
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


class TestCartTrackStubFilter:
    """Phase 1 of the cart-track topology refactor — short runs
    stay ``CORRIDOR`` so the painter doesn't decorate stubs that
    read as track debris rather than rail."""

    def test_min_track_run_length_constant(self):
        # The constant defines the threshold; the rest of this
        # class assumes it's 3 tiles. Bumping the constant should
        # update both this test and the docstring of
        # ``add_cart_tracks``.
        assert MIN_TRACK_RUN_LENGTH == 3

    def test_one_tile_stub_stays_corridor(self):
        level = _empty_level(8, 4)
        _stamp_corridor_run(level, [(2, 2)])
        add_cart_tracks(level, random.Random(0))
        assert (
            level.tiles[2][2].surface_type
            is SurfaceType.CORRIDOR
        )

    def test_two_tile_stub_stays_corridor(self):
        level = _empty_level(8, 4)
        _stamp_corridor_run(level, [(2, 2), (3, 2)])
        add_cart_tracks(level, random.Random(0))
        for x in (2, 3):
            assert (
                level.tiles[2][x].surface_type
                is SurfaceType.CORRIDOR
            )

    def test_three_tile_run_upgrades_to_track(self):
        level = _empty_level(8, 4)
        _stamp_corridor_run(level, [(2, 2), (3, 2), (4, 2)])
        add_cart_tracks(level, random.Random(0))
        for x in (2, 3, 4):
            assert (
                level.tiles[2][x].surface_type
                is SurfaceType.TRACK
            )

    def test_l_shaped_run_counts_total_tiles(self):
        # Three-tile L-shape: still ≥ MIN, all three upgrade.
        level = _empty_level(8, 4)
        _stamp_corridor_run(level, [(2, 1), (2, 2), (3, 2)])
        add_cart_tracks(level, random.Random(0))
        for x, y in [(2, 1), (2, 2), (3, 2)]:
            assert (
                level.tiles[y][x].surface_type
                is SurfaceType.TRACK
            )

    def test_disconnected_runs_are_separate(self):
        # Two 2-tile runs separated by a void column. Both stay
        # CORRIDOR even though their combined tile count is 4 —
        # 4-connectivity gates the threshold per run.
        level = _empty_level(10, 4)
        _stamp_corridor_run(level, [(1, 2), (2, 2)])
        _stamp_corridor_run(level, [(7, 2), (8, 2)])
        add_cart_tracks(level, random.Random(0))
        for x in (1, 2, 7, 8):
            assert (
                level.tiles[2][x].surface_type
                is SurfaceType.CORRIDOR
            )

    def test_door_features_block_track_upgrade(self):
        # A corridor tile carrying a door feature is not eligible;
        # the run on each side counts toward its own length.
        level = _empty_level(10, 4)
        _stamp_corridor_run(
            level, [(1, 2), (2, 2), (3, 2), (4, 2), (5, 2)],
        )
        # Door at (3, 2) splits the 5-tile run into two 2-tile
        # halves -- both halves stay CORRIDOR.
        level.tiles[2][3].feature = "door_closed"
        add_cart_tracks(level, random.Random(0))
        for x in (1, 2, 4, 5):
            assert (
                level.tiles[2][x].surface_type
                is SurfaceType.CORRIDOR
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

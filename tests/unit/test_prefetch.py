"""Tests for background floor pre-generation on stair proximity."""

from __future__ import annotations

import random
import threading
import time

import pytest

from nhc.core import game_ticks
from nhc.core.ecs import World
from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, Terrain, Tile, Room, Rect
from nhc.dungeon.populator import populate_level
from nhc.entities.components import Position


# ── Helpers ────────────────────────────────────────────────────────

def _make_level(depth: int = 1, width: int = 20, height: int = 20):
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(width)]
             for _ in range(height)]
    return Level(
        id=f"depth_{depth}", name=f"Test Level {depth}", depth=depth,
        width=width, height=height, tiles=tiles,
        rooms=[Room(id="r1", rect=Rect(1, 1, 10, 10), tags=["entry"])],
    )


class FakeGame:
    """Minimal Game stub for tick testing."""

    def __init__(self, level=None):
        self.world = World()
        self.level = level or _make_level()
        self.player_id = self.world.create_entity({
            "Position": Position(x=5, y=5, level_id=self.level.id),
        })
        self._floor_cache: dict[int, tuple] = {}
        self._prefetch_depth: int | None = None
        self._prefetch_result: Level | None = None
        self._prefetch_thread: threading.Thread | None = None
        self.shape_variety = 0.3
        self.seed = 42

    def _start_prefetch(self, depth: int) -> None:
        """Spawn a background thread to pre-generate a floor."""
        seed = (self.seed or 0) + depth * 997
        sv = self.shape_variety

        def _generate() -> None:
            rng = random.Random(seed)
            params = GenerationParams(depth=depth, shape_variety=sv)
            gen = BSPGenerator()
            level = gen.generate(params, rng=rng)
            populate_level(level, rng=rng)
            self._prefetch_result = level
            self._prefetch_thread = None

        self._prefetch_depth = depth
        self._prefetch_thread = threading.Thread(
            target=_generate, daemon=True,
        )
        self._prefetch_thread.start()


# ── Tests ──────────────────────────────────────────────────────────

class TestStairsProximityTick:
    """tick_stairs_proximity detects nearby downstairs."""

    def test_triggers_prefetch_when_near_stairs(self):
        level = _make_level(depth=2)
        level.tiles[8][5].feature = "stairs_down"  # 3 tiles from player
        game = FakeGame(level)

        game_ticks.tick_stairs_proximity(game)

        assert game._prefetch_depth == 3
        # Wait for thread to finish
        if game._prefetch_thread:
            game._prefetch_thread.join(timeout=10)
        assert game._prefetch_result is not None
        assert game._prefetch_result.depth == 3

    def test_no_prefetch_when_far_from_stairs(self):
        level = _make_level(depth=1, width=30, height=30)
        level.tiles[20][20].feature = "stairs_down"  # far from (5,5)
        game = FakeGame(level)

        game_ticks.tick_stairs_proximity(game)

        assert game._prefetch_depth is None
        assert game._prefetch_result is None

    def test_no_prefetch_when_depth_already_cached(self):
        level = _make_level(depth=1)
        level.tiles[6][5].feature = "stairs_down"  # adjacent
        game = FakeGame(level)
        game._floor_cache[2] = ("cached", {})

        game_ticks.tick_stairs_proximity(game)

        assert game._prefetch_depth is None

    def test_no_duplicate_prefetch(self):
        level = _make_level(depth=1)
        level.tiles[6][5].feature = "stairs_down"
        game = FakeGame(level)

        game_ticks.tick_stairs_proximity(game)
        if game._prefetch_thread:
            game._prefetch_thread.join(timeout=10)
        assert game._prefetch_depth == 2

        # Second call should not restart prefetch
        game._prefetch_result = "already_done"
        game_ticks.tick_stairs_proximity(game)
        assert game._prefetch_result == "already_done"

    def test_skips_when_prefetch_thread_running(self):
        level = _make_level(depth=1)
        level.tiles[6][5].feature = "stairs_down"
        game = FakeGame(level)
        # Simulate a running thread
        game._prefetch_thread = threading.Thread(target=lambda: None)

        game_ticks.tick_stairs_proximity(game)

        # Should not have changed prefetch_depth
        assert game._prefetch_depth is None


class TestBSPGeneratorRng:
    """BSPGenerator.generate accepts an external rng."""

    def test_generate_with_custom_rng(self):
        rng = random.Random(12345)
        params = GenerationParams(depth=1)
        gen = BSPGenerator()

        level = gen.generate(params, rng=rng)

        assert level.depth == 1
        assert level.width > 0
        assert len(level.rooms) > 0

    def test_generate_deterministic_with_same_seed(self):
        params = GenerationParams(depth=3)
        gen = BSPGenerator()

        rng1 = random.Random(99999)
        level1 = gen.generate(params, rng=rng1)

        rng2 = random.Random(99999)
        level2 = gen.generate(params, rng=rng2)

        assert len(level1.rooms) == len(level2.rooms)
        for r1, r2 in zip(level1.rooms, level2.rooms):
            assert r1.rect == r2.rect


class TestPopulateLevelRng:
    """populate_level accepts an external rng."""

    def test_populate_with_custom_rng(self):
        rng = random.Random(54321)
        params = GenerationParams(depth=2)
        gen = BSPGenerator()
        level = gen.generate(params, rng=rng)

        rng2 = random.Random(11111)
        populate_level(level, rng=rng2)

        assert len(level.entities) > 0

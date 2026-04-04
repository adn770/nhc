"""Tests for the pure dungeon generation pipeline.

The pipeline must be a self-contained function that can run inside a
ProcessPoolExecutor worker: no globals, no thread-locals mutation,
deterministic by seed, and its output must be picklable.
"""

from __future__ import annotations

import pickle
from concurrent.futures import ProcessPoolExecutor

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level
from nhc.dungeon.pipeline import generate_level


def _params(seed: int, theme: str = "dungeon") -> GenerationParams:
    return GenerationParams(
        width=40,
        height=30,
        depth=1,
        theme=theme,
        seed=seed,
        shape_variety=0.3,
    )


class TestGenerateLevelPure:
    def test_returns_level_with_rooms_and_entities(self):
        level = generate_level(_params(seed=1))
        assert isinstance(level, Level)
        assert level.width == 40
        assert level.height == 30
        assert len(level.rooms) > 0
        # populate_level should add creatures and items
        assert len(level.entities) > 0

    def test_generates_cave_theme(self):
        level = generate_level(_params(seed=1, theme="cave"))
        assert isinstance(level, Level)
        assert level.width == 40

    def test_deterministic_by_seed(self):
        a = generate_level(_params(seed=12345))
        b = generate_level(_params(seed=12345))
        assert len(a.rooms) == len(b.rooms)
        assert len(a.entities) == len(b.entities)
        # Tile feature patterns match
        features_a = [
            (x, y, a.tile_at(x, y).feature)
            for y in range(a.height)
            for x in range(a.width)
            if a.tile_at(x, y) and a.tile_at(x, y).feature
        ]
        features_b = [
            (x, y, b.tile_at(x, y).feature)
            for y in range(b.height)
            for x in range(b.width)
            if b.tile_at(x, y) and b.tile_at(x, y).feature
        ]
        assert features_a == features_b

    def test_different_seeds_differ(self):
        a = generate_level(_params(seed=1))
        b = generate_level(_params(seed=2))
        # Extremely unlikely to match
        assert (len(a.rooms), len(a.entities)) != (
            len(b.rooms),
            len(b.entities),
        ) or a.rooms[0].rect != b.rooms[0].rect

    def test_result_is_picklable(self):
        level = generate_level(_params(seed=42))
        blob = pickle.dumps(level)
        restored = pickle.loads(blob)
        assert restored.width == level.width
        assert len(restored.rooms) == len(level.rooms)
        assert len(restored.entities) == len(level.entities)

    def test_does_not_mutate_thread_local_rng_for_caller(self):
        """The pipeline must use its own local RNG, not the thread-local.

        Otherwise, pool workers would step on each other's RNG state and
        main-process code that holds a reference to get_rng() would see
        unexpected advances.
        """
        from nhc.utils.rng import get_rng, set_seed

        set_seed(999)
        before = get_rng().random()
        set_seed(999)
        generate_level(_params(seed=1))
        after = get_rng().random()
        assert before == after


class TestGenerateLevelInPool:
    def test_runs_in_process_pool(self):
        with ProcessPoolExecutor(max_workers=2) as pool:
            fut_a = pool.submit(generate_level, _params(seed=100))
            fut_b = pool.submit(generate_level, _params(seed=200))
            level_a = fut_a.result(timeout=30)
            level_b = fut_b.result(timeout=30)
        assert isinstance(level_a, Level)
        assert isinstance(level_b, Level)
        # Different seeds → different layouts
        assert level_a.rooms[0].rect != level_b.rooms[0].rect or len(
            level_a.rooms
        ) != len(level_b.rooms)

    def test_concurrent_pool_submissions_are_deterministic(self):
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(generate_level, _params(seed=s))
                for s in (10, 20, 30, 40)
            ]
            levels = [f.result(timeout=30) for f in futures]

        # Re-run serially; results must match concurrent ones
        serial = [generate_level(_params(seed=s)) for s in (10, 20, 30, 40)]
        for a, b in zip(levels, serial):
            assert len(a.rooms) == len(b.rooms)
            assert len(a.entities) == len(b.entities)

"""Tests for Game.initialize() with an optional executor.

When an executor is passed, generation must run in the pool (so a
single-worker gevent server stays responsive). When None, generation
runs inline (preserves CLI and non-web callers).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ProcessPoolExecutor

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.i18n import init as i18n_init


class _FakeClient:
    """Permissive GameClient stand-in — accepts any sync/async call."""
    game_mode = "classic"
    lang = "en"
    edge_doors = False

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def _async(*a, **kw):
            return None

        def _sync(*a, **kw):
            return None

        # Return an async-callable by default; sync callers will get
        # a coroutine they don't await, which Game's initialize path
        # tolerates for these placeholder hooks.
        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


@pytest.fixture
def make_game(tmp_path):
    def _make(seed=12345):
        g = Game(
            client=_FakeClient(),
            backend=None,
            game_mode="classic",
            save_dir=tmp_path,
            seed=seed,
        )
        return g
    return _make


class TestInitializeInline:
    def test_initialize_without_executor_runs_inline(self, make_game):
        game = make_game(seed=111)
        asyncio.run(game.initialize(generate=True))
        assert game.level is not None
        assert len(game.level.rooms) > 0
        assert game.player_id is not None


class TestInitializeWithExecutor:
    def test_initialize_with_executor_produces_same_result(self, make_game):
        """Same seed, executor vs inline → identical level layout."""
        inline = make_game(seed=222)
        asyncio.run(inline.initialize(generate=True))

        with ProcessPoolExecutor(max_workers=1) as pool:
            pooled = make_game(seed=222)
            asyncio.run(pooled.initialize(generate=True, executor=pool))

        assert inline.level is not None
        assert pooled.level is not None
        assert len(inline.level.rooms) == len(pooled.level.rooms)
        assert len(inline.level.entities) == len(pooled.level.entities)
        assert inline.level.width == pooled.level.width

    def test_initialize_concurrent_with_shared_pool(self, tmp_path):
        """Two games initialized concurrently through the same pool
        both succeed with distinct seeds → distinct levels."""
        async def _run():
            with ProcessPoolExecutor(max_workers=2) as pool:
                g1 = Game(
                    client=_FakeClient(),
                    backend=None,
                    save_dir=tmp_path / "a",
                    seed=1001,
                )
                g2 = Game(
                    client=_FakeClient(),
                    backend=None,
                    save_dir=tmp_path / "b",
                    seed=2002,
                )
                (tmp_path / "a").mkdir()
                (tmp_path / "b").mkdir()
                await asyncio.gather(
                    g1.initialize(generate=True, executor=pool),
                    g2.initialize(generate=True, executor=pool),
                )
                return g1, g2

        g1, g2 = asyncio.run(_run())
        assert g1.level is not None and g2.level is not None
        # Different seeds produce different layouts
        assert g1.seed != g2.seed
        assert (
            g1.level.rooms[0].rect != g2.level.rooms[0].rect
            or len(g1.level.rooms) != len(g2.level.rooms)
        )

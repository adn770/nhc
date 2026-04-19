"""Rumor pool refresh on settlement revisit.

The first-visit auto-seed from ``_maybe_seed_rumors`` keeps the
pool static forever otherwise: a player who visits the inn
daily sees the same three leads until they bump them all. With
a cooldown, a revisit after N days tops up the pool with fresh
rumors (merged onto any unconsumed leads).

Behavior:
  * empty pool    -> always seed (unchanged)
  * non-empty + cooldown expired -> append new rumors
  * non-empty + cooldown not yet elapsed -> no-op
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType, Rumor
from nhc.i18n import init as i18n_init


class _FakeClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _seed_settlement(g: Game):
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CITY
    cell.dungeon = DungeonRef(template="procedural:settlement")
    return coord


# ---------------------------------------------------------------------------
# Same-day revisit: no refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_day_revisit_keeps_rumor_pool_intact(tmp_path) -> None:
    g = _make_game(tmp_path)
    _seed_settlement(g)
    await g.enter_hex_feature()
    first = list(g.hex_world.active_rumors)
    assert first, "first visit seeds"
    await g.exit_dungeon_to_hex()
    # Re-enter right away: clock hasn't moved.
    await g.enter_hex_feature()
    assert g.hex_world.active_rumors == first, (
        "same-day revisit should not refresh rumors"
    )


# ---------------------------------------------------------------------------
# Cooldown expired: top-up
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revisit_after_cooldown_adds_new_rumors(tmp_path) -> None:
    g = _make_game(tmp_path)
    _seed_settlement(g)
    await g.enter_hex_feature()
    first = list(g.hex_world.active_rumors)
    count_before = len(first)
    await g.exit_dungeon_to_hex()
    # Age the clock past the cooldown (3 days = 12 segments).
    g.hex_world.advance_clock(12)
    # Re-enter: fresh rumors append (unconsumed ones survive).
    g._floor_cache.clear()
    await g.enter_hex_feature()
    assert len(g.hex_world.active_rumors) > count_before
    # The first-visit rumors still live in the pool.
    first_ids = {r.id for r in first}
    current_ids = {r.id for r in g.hex_world.active_rumors}
    assert first_ids <= current_ids


# ---------------------------------------------------------------------------
# Existing preset respected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_existing_pool_does_not_block_cooldown_refresh(
    tmp_path,
) -> None:
    """A manually-planted rumor should coexist with a cooldown
    top-up: after enough days, the fresh pool appends, preset
    stays."""
    g = _make_game(tmp_path)
    preset = Rumor(
        id="preset", text="rumor.true_feature", truth=True,
    )
    g.hex_world.active_rumors = [preset]
    _seed_settlement(g)
    # First visit: preset survives (pool wasn't empty).
    await g.enter_hex_feature()
    assert preset in g.hex_world.active_rumors
    await g.exit_dungeon_to_hex()
    # Age past cooldown and re-enter.
    g.hex_world.advance_clock(12)
    g._floor_cache.clear()
    await g.enter_hex_feature()
    assert preset in g.hex_world.active_rumors
    # Fresh ones got added.
    assert len(g.hex_world.active_rumors) > 1

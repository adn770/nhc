"""Panic-flee action (M-2.8): escape a hex-mode dungeon at a cost.

Normal dungeon exit walks back to the entry tile
(``Game.exit_dungeon_to_hex``). Panic-flee works from anywhere
inside the dungeon but exacts a cost on the way out: the player
takes a 1d6 damage roll and the overland day clock advances one
half-day segment. The intent is a "you can always bail" safety
valve that still discourages spamming it.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
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


def _make_hex_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


async def _enter_cave(g: Game) -> HexCoord:
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave")
    await g.enter_hex_feature()
    return coord


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_panic_flee_pops_back_to_overland(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    await _enter_cave(g)
    assert g.level is not None
    ok = await g.panic_flee()
    assert ok is True
    assert g.level is None, "panic flee must pop the dungeon"
    assert g.hex_world is not None
    assert g.hex_player_position is not None


@pytest.mark.asyncio
async def test_panic_flee_deals_damage(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    await _enter_cave(g)
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    # Seeded RNG so the 1d6 roll is deterministic.
    g._encounter_rng = random.Random(1)
    await g.panic_flee()
    assert hp.current < hp_before, (
        f"panic flee should shave hp, before={hp_before} "
        f"after={hp.current}"
    )
    assert hp.current >= 0, "panic flee shouldn't drop hp below 0"


@pytest.mark.asyncio
async def test_panic_flee_advances_day_clock(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    await _enter_cave(g)
    clock_before = (g.hex_world.day, g.hex_world.time)
    await g.panic_flee()
    clock_after = (g.hex_world.day, g.hex_world.time)
    assert clock_after != clock_before, (
        f"panic flee should advance the day clock, "
        f"before={clock_before} after={clock_after}"
    )


@pytest.mark.asyncio
async def test_panic_flee_noop_on_overland(tmp_path) -> None:
    """Nothing to flee from when already on the overland; returns
    False without touching HP or the clock."""
    g = _make_hex_game(tmp_path)
    assert g.level is None
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    clock_before = (g.hex_world.day, g.hex_world.time)

    ok = await g.panic_flee()
    assert ok is False
    assert hp.current == hp_before
    assert (g.hex_world.day, g.hex_world.time) == clock_before


@pytest.mark.asyncio
async def test_panic_flee_wont_kill_player(tmp_path) -> None:
    """Floor the HP roll at current - 1 so panic-flee never ends
    the run outright -- the player is meant to escape bleeding,
    not die on the way out."""
    g = _make_hex_game(tmp_path)
    await _enter_cave(g)
    hp = g.world.get_component(g.player_id, "Health")
    hp.current = 1  # about to die
    await g.panic_flee()
    assert hp.current >= 1, (
        f"panic flee must not reduce a 1-hp player below 1, "
        f"got {hp.current}"
    )

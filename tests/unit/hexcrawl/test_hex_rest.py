"""Overland rest action restores HP alongside the clock advance.

Before this fix, ``hex_rest`` only advanced the overland day
clock (four half-day segments) and left HP untouched -- a
substantial time investment with no tactical payoff. The fix
brings HP to maximum on rest so the player can actually heal
between dungeons.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
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


async def _rest_via_turn(g: Game) -> None:
    async def _fake():
        return ("hex_rest", None)
    g.renderer.get_input = _fake
    await g._process_hex_turn()


@pytest.mark.asyncio
async def test_rest_restores_hp_to_max(tmp_path) -> None:
    g = _make_game(tmp_path)
    hp = g.world.get_component(g.player_id, "Health")
    hp.current = 1  # near-dead
    await _rest_via_turn(g)
    assert hp.current == hp.maximum


@pytest.mark.asyncio
async def test_rest_still_advances_the_day_clock(tmp_path) -> None:
    g = _make_game(tmp_path)
    day_before = g.hex_world.day
    await _rest_via_turn(g)
    assert g.hex_world.day == day_before + 1


@pytest.mark.asyncio
async def test_rest_noop_if_already_full_hp(tmp_path) -> None:
    """Full-HP rest still ticks the clock (that's the cost) but
    doesn't error or overheal."""
    g = _make_game(tmp_path)
    hp = g.world.get_component(g.player_id, "Health")
    hp.current = hp.maximum
    await _rest_via_turn(g)
    assert hp.current == hp.maximum

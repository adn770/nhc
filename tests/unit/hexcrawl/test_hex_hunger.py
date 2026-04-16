"""Hunger ticks on overland travel.

The dungeon-side hunger tick already decrements Hunger.current
each turn and applies starvation damage at the low end. Hex
turns run a different branch of the game loop (_process_hex_turn)
so without this wiring the player never got hungry while
travelling.

Additional wrinkles tuned here:

* Resting (hex_rest) refills hunger to max along with HP.
* Entering a feature hex doesn't double-tick hunger (one event
  per hex turn, regardless of whether the player moved or
  entered).
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.components import Hunger
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import HexFeatureType
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
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _pick_open_neighbour(g: Game) -> HexCoord:
    for n in neighbors(g.hex_player_position):
        cell = g.hex_world.cells.get(n)
        if cell is None:
            continue
        if cell.feature is not HexFeatureType.NONE:
            continue
        return n
    raise AssertionError("no open adjacent hex")


async def _do_step(g: Game, target: HexCoord) -> None:
    origin = g.hex_player_position
    dq = target.q - origin.q
    dr = target.r - origin.r

    async def _fake():
        return ("hex_step", (dq, dr))
    g.renderer.get_input = _fake
    await g._process_hex_turn()


async def _do_rest(g: Game) -> None:
    async def _fake():
        return ("hex_rest", None)
    g.renderer.get_input = _fake
    await g._process_hex_turn()


# ---------------------------------------------------------------------------
# Steps tick hunger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hex_step_decrements_hunger(tmp_path) -> None:
    g = _make_game(tmp_path)
    hunger = g.world.get_component(g.player_id, "Hunger")
    assert hunger is not None
    start = hunger.current
    # Force an open target by clearing any feature.
    target = _pick_open_neighbour(g)
    g.encounter_rate = 0.0  # keep the test focused on hunger
    await _do_step(g, target)
    assert hunger.current == start - 1, (
        f"hunger should tick by 1 per hex step, got {hunger.current} "
        f"from {start}"
    )


# ---------------------------------------------------------------------------
# Rest refills hunger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hex_rest_refills_hunger(tmp_path) -> None:
    g = _make_game(tmp_path)
    hunger = g.world.get_component(g.player_id, "Hunger")
    hunger.current = 200  # hungry-zone
    await _do_rest(g)
    assert hunger.current == hunger.maximum, (
        "rest should refill hunger alongside HP"
    )


# ---------------------------------------------------------------------------
# Starvation damages HP on travel when hunger bottoms out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_starving_player_loses_hp_on_step(tmp_path) -> None:
    g = _make_game(tmp_path)
    hunger = g.world.get_component(g.player_id, "Hunger")
    hunger.current = 0  # starving
    hp = g.world.get_component(g.player_id, "Health")
    # Ensure we're on a multi-of-5 turn so the starving tick
    # fires deterministically.
    g.turn = 5
    g.encounter_rate = 0.0
    target = _pick_open_neighbour(g)
    hp_before = hp.current
    await _do_step(g, target)
    assert hp.current < hp_before, (
        "starving + step should shave at least 1 HP"
    )

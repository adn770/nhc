"""Fight / Flee / Talk prompt after a hex step.

The auto-roll from apply_hex_step stages an Encounter on
Game.pending_encounter. The next piece -- surfacing it to the
player -- runs inside _process_hex_turn: show the three-option
menu via renderer.show_selection_menu, then dispatch the choice
through resolve_encounter.

With the whole pipeline in place, stepping into danger fires a
prompt, the player's pick actually resolves, and no prompt
appears when no encounter was rolled.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.encounter import ARENA_TAG
from nhc.hexcrawl.encounter_pipeline import Encounter, EncounterChoice
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import Biome, HexFeatureType
from nhc.i18n import init as i18n_init


class _FakeClient:
    """Renderer stub that captures show_selection_menu calls."""

    game_mode = "classic"
    lang = "en"
    edge_doors = False

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.menu_calls: list[tuple] = []
        self.menu_picks: list = []

    def show_selection_menu(self, title, options):
        self.menu_calls.append((title, list(options)))
        if not self.menu_picks:
            return options[0][0] if options else None
        return self.menu_picks.pop(0)

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


def _make_hex_game(tmp_path, client: _FakeClient) -> Game:
    g = Game(
        client=client,
        backend=None,
        style="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _pick_open_neighbour(g: Game) -> HexCoord:
    """Return an adjacent in-shape non-feature hex so the step
    lands in the wild (not on top of a feature / settlement)."""
    origin = g.hex_player_position
    for n in neighbors(origin):
        cell = g.hex_world.cells.get(n)
        if cell is None:
            continue
        if cell.feature is not HexFeatureType.NONE:
            continue
        return n
    # Fall back: clear a neighbour's feature so the test still
    # has a valid target.
    for n in neighbors(origin):
        if n in g.hex_world.cells:
            g.hex_world.cells[n].feature = HexFeatureType.NONE
            g.hex_world.cells[n].dungeon = None
            return n
    raise AssertionError("no adjacent in-shape hex")


# ---------------------------------------------------------------------------
# Prompt shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_with_pending_encounter_fires_prompt(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    # Force a guaranteed encounter so the prompt is deterministic.
    g.encounter_rate = 1.0
    g._encounter_rng = random.Random(1)
    target = _pick_open_neighbour(g)
    # Pre-queue TALK so the flow resolves cleanly.
    client.menu_picks = [EncounterChoice.TALK.value]
    # Drive the turn via the same entry point the game loop uses.
    ok = await _step_via_turn(g, target)
    assert ok == "moved"
    assert client.menu_calls, "encounter prompt should fire"
    title, options = client.menu_calls[0]
    option_ids = [opt[0] for opt in options]
    assert EncounterChoice.FIGHT.value in option_ids
    assert EncounterChoice.FLEE.value in option_ids
    assert EncounterChoice.TALK.value in option_ids
    # And the pick flowed through: pending cleared after resolve.
    assert g.pending_encounter is None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fight_pick_loads_arena(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    g.encounter_rate = 1.0
    g._encounter_rng = random.Random(1)
    target = _pick_open_neighbour(g)
    client.menu_picks = [EncounterChoice.FIGHT.value]
    await _step_via_turn(g, target)
    assert g.level is not None, "FIGHT should load the arena level"
    assert any(ARENA_TAG in r.tags for r in g.level.rooms)


@pytest.mark.asyncio
async def test_flee_pick_deals_damage(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    g.encounter_rate = 1.0
    g._encounter_rng = random.Random(1)
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    target = _pick_open_neighbour(g)
    client.menu_picks = [EncounterChoice.FLEE.value]
    await _step_via_turn(g, target)
    assert g.level is None, "FLEE keeps us on the overland"
    assert hp.current < hp_before, "FLEE should bruise the player"


# ---------------------------------------------------------------------------
# No prompt when nothing to ask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_without_encounter_skips_prompt(tmp_path) -> None:
    client = _FakeClient()
    g = _make_hex_game(tmp_path, client)
    g.encounter_rate = 0.0  # never rolls
    target = _pick_open_neighbour(g)
    await _step_via_turn(g, target)
    assert g.pending_encounter is None
    assert client.menu_calls == []


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


async def _step_via_turn(g: Game, target: HexCoord) -> str:
    """Dispatch a hex_step intent through _process_hex_turn.

    Monkeypatches renderer.get_input to feed the synthetic
    intent; restores it on exit.
    """
    origin = g.hex_player_position
    dq = target.q - origin.q
    dr = target.r - origin.r

    async def _fake_get_input():
        return ("hex_step", (dq, dr))

    g.renderer.get_input = _fake_get_input
    return await g._process_hex_turn()

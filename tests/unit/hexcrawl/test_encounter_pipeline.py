"""Encounter pipeline (M-2.6): Fight / Flee / Talk.

``roll_encounter`` decides whether a hex step surfaces an
encounter. When one fires, the player picks Fight / Flee / Talk
and :meth:`Game.resolve_encounter` dispatches:

* Fight → push an arena Level (from M-2.5) and enter it.
* Flee → stay on the overland and take a small damage roll.
* Talk → peacefully resolve; the full LLM dialog ships with a
  later UI polish pass.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.encounter import ARENA_TAG
from nhc.hexcrawl.encounter_pipeline import (
    Encounter,
    EncounterChoice,
    roll_encounter,
)
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import Biome
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


# ---------------------------------------------------------------------------
# roll_encounter
# ---------------------------------------------------------------------------


def test_roll_encounter_none_when_rate_zero() -> None:
    """Rate 0 always returns None regardless of RNG draws."""
    rng = random.Random(1)
    assert roll_encounter(Biome.GREENLANDS, rng, encounter_rate=0.0) is None


def test_roll_encounter_emits_when_rate_one() -> None:
    """Rate 1 always returns a populated Encounter."""
    rng = random.Random(1)
    enc = roll_encounter(Biome.FOREST, rng, encounter_rate=1.0)
    assert isinstance(enc, Encounter)
    assert enc.biome is Biome.FOREST
    assert len(enc.creatures) >= 1


def test_roll_encounter_uses_biome_pool() -> None:
    """The rolled creatures are drawn from the biome's default pool."""
    from nhc.hexcrawl.encounter import DEFAULT_BIOME_POOLS
    rng = random.Random(1)
    enc = roll_encounter(Biome.ICELANDS, rng, encounter_rate=1.0)
    allowed = set(DEFAULT_BIOME_POOLS[Biome.ICELANDS])
    assert set(enc.creatures).issubset(allowed), (
        f"creatures {enc.creatures} not a subset of {allowed}"
    )


# ---------------------------------------------------------------------------
# Fight branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fight_loads_arena_and_spawns_creatures(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    enc = Encounter(
        biome=Biome.GREENLANDS,
        creatures=["goblin", "kobold"],
    )
    g.pending_encounter = enc
    ok = await g.resolve_encounter(EncounterChoice.FIGHT)
    assert ok is True
    assert g.level is not None, "FIGHT should load the arena level"
    assert ARENA_TAG in g.level.rooms[0].tags
    # Two creatures with AI components should be in the ECS world.
    ai_count = sum(1 for _ in g.world.query("AI"))
    assert ai_count >= 2
    # Pending encounter is cleared.
    assert g.pending_encounter is None


@pytest.mark.asyncio
async def test_fight_places_player_on_stairs_up(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS, creatures=["goblin"],
    )
    await g.resolve_encounter(EncounterChoice.FIGHT)
    ppos = g.world.get_component(g.player_id, "Position")
    tile = g.level.tile_at(ppos.x, ppos.y)
    assert tile is not None and tile.feature == "stairs_up"


# ---------------------------------------------------------------------------
# Flee branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flee_clears_encounter_and_stays_on_overland(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS, creatures=["goblin"],
    )
    assert g.level is None  # overland
    ok = await g.resolve_encounter(EncounterChoice.FLEE)
    assert ok is True
    assert g.level is None, "FLEE must keep us on the overland"
    assert g.pending_encounter is None


@pytest.mark.asyncio
async def test_flee_deals_some_damage(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS, creatures=["goblin"],
    )
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    # Seed the encounter RNG so the roll is deterministic.
    g._encounter_rng = random.Random(1)
    await g.resolve_encounter(EncounterChoice.FLEE)
    assert hp.current < hp_before, (
        f"FLEE should shave at least 1 hp, before={hp_before} "
        f"after={hp.current}"
    )
    assert hp.current >= 0


# ---------------------------------------------------------------------------
# Talk branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_talk_clears_encounter_without_damage(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS, creatures=["goblin"],
    )
    hp = g.world.get_component(g.player_id, "Health")
    hp_before = hp.current
    ok = await g.resolve_encounter(EncounterChoice.TALK)
    assert ok is True
    assert g.pending_encounter is None
    assert g.level is None
    assert hp.current == hp_before, "TALK must not deal damage"


@pytest.mark.asyncio
async def test_resolve_no_pending_encounter_is_noop(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    assert g.pending_encounter is None
    ok = await g.resolve_encounter(EncounterChoice.FIGHT)
    assert ok is False
    assert g.level is None

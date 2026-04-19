"""Auto-roll encounters on :meth:`Game.apply_hex_step`.

Each successful overland step rolls against
``Game.encounter_rate``; a hit stages an :class:`Encounter` on
``Game.pending_encounter`` so the next turn's input cycle can
prompt the Fight / Flee / Talk choice. God-mode and zero-rate
configurations short-circuit the roll.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.encounter_pipeline import Encounter
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
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


def _make_hex_game(tmp_path, *, god: bool = False) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
        god_mode=god,
    )
    g.initialize()
    return g


def _pick_neighbour(g: Game) -> HexCoord:
    """Return an in-shape neighbour the player can step to."""
    origin = g.hex_player_position
    for n in neighbors(origin):
        if g.hex_world is not None and n in g.hex_world.cells:
            return n
    raise AssertionError("no adjacent in-shape hex for the step test")


# ---------------------------------------------------------------------------
# Happy path: step triggers encounter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_rolls_encounter_at_full_rate(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.encounter_rate = 1.0
    # Seed the encounter RNG so the creature pack is deterministic.
    g._encounter_rng = random.Random(7)
    # Make sure the target isn't a feature hex (feature hexes
    # invite "enter" rather than "encounter").
    target = _pick_neighbour(g)
    g.hex_world.cells[target].feature = HexFeatureType.NONE
    g.hex_world.cells[target].dungeon = None

    assert g.pending_encounter is None
    ok = await g.apply_hex_step(target)
    assert ok is True
    assert isinstance(g.pending_encounter, Encounter)
    assert g.pending_encounter.creatures, (
        "rolled encounter must carry at least one creature"
    )


# ---------------------------------------------------------------------------
# Guards: god mode, zero rate, feature hexes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_skips_encounter_under_god_mode(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=True)
    g.encounter_rate = 1.0
    g._encounter_rng = random.Random(7)
    target = _pick_neighbour(g)
    g.hex_world.cells[target].feature = HexFeatureType.NONE
    g.hex_world.cells[target].dungeon = None

    await g.apply_hex_step(target)
    assert g.pending_encounter is None, (
        "god mode must disable encounter rolls"
    )


@pytest.mark.asyncio
async def test_step_skips_encounter_at_rate_zero(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    g.encounter_rate = 0.0
    target = _pick_neighbour(g)
    g.hex_world.cells[target].feature = HexFeatureType.NONE
    g.hex_world.cells[target].dungeon = None

    await g.apply_hex_step(target)
    assert g.pending_encounter is None


@pytest.mark.asyncio
async def test_step_skips_encounter_on_feature_hex(tmp_path) -> None:
    """Stepping onto a feature hex (cave / city / etc.) shouldn't
    fire an encounter -- the player is about to pick enter-or-not."""
    from nhc.hexcrawl.model import DungeonRef
    g = _make_hex_game(tmp_path)
    g.encounter_rate = 1.0
    g._encounter_rng = random.Random(7)
    target = _pick_neighbour(g)
    g.hex_world.cells[target].feature = HexFeatureType.CAVE
    g.hex_world.cells[target].dungeon = DungeonRef(
        template="procedural:cave",
    )

    await g.apply_hex_step(target)
    assert g.pending_encounter is None, (
        "feature hexes invite 'enter', not encounters"
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seeded_encounter_rng_is_reproducible(tmp_path) -> None:
    g1 = _make_hex_game(tmp_path)
    g1.encounter_rate = 1.0
    g1._encounter_rng = random.Random(42)
    target1 = _pick_neighbour(g1)
    g1.hex_world.cells[target1].feature = HexFeatureType.NONE
    g1.hex_world.cells[target1].dungeon = None
    await g1.apply_hex_step(target1)

    g2 = _make_hex_game(tmp_path / "sub")
    g2.encounter_rate = 1.0
    g2._encounter_rng = random.Random(42)
    target2 = _pick_neighbour(g2)
    g2.hex_world.cells[target2].feature = HexFeatureType.NONE
    g2.hex_world.cells[target2].dungeon = None
    await g2.apply_hex_step(target2)

    assert g1.pending_encounter is not None
    assert g2.pending_encounter is not None
    assert g1.pending_encounter.biome == g2.pending_encounter.biome
    assert g1.pending_encounter.creatures == g2.pending_encounter.creatures

"""Fight branch post-combat cleanup.

Today FIGHT loads an arena :class:`Level` and the player has to
Shift+L manually once all foes are dead. That's clumsy -- the
arena is a one-shot scratch space, not a persistent dungeon.

With this hook, the dungeon turn loop checks after each round:
if the current level is an arena (:data:`ARENA_TAG`) and no AI
entities remain on it, auto-pop back to the overland with a
victory message.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.encounter import ARENA_TAG
from nhc.hexcrawl.encounter_pipeline import Encounter, EncounterChoice
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


def _make_arena_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    g.pending_encounter = Encounter(
        biome=Biome.GREENLANDS,
        creatures=["goblin", "kobold"],
    )
    return g


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _kill_all_ai(g: Game) -> None:
    victims = [eid for eid, _ in g.world.query("AI")]
    for eid in victims:
        g.world.destroy_entity(eid)


@pytest.mark.asyncio
async def test_arena_auto_exits_when_all_foes_dead(tmp_path) -> None:
    g = _make_arena_game(tmp_path)
    await g.resolve_encounter(EncounterChoice.FIGHT)
    assert g.level is not None
    assert any(ARENA_TAG in r.tags for r in g.level.rooms)
    _kill_all_ai(g)
    assert g._maybe_exit_cleared_arena() is True
    assert g.level is None, "arena should auto-pop to overland"


@pytest.mark.asyncio
async def test_arena_stays_while_foes_alive(tmp_path) -> None:
    g = _make_arena_game(tmp_path)
    await g.resolve_encounter(EncounterChoice.FIGHT)
    # Pretend we only killed one of the two.
    live = list(g.world.query("AI"))
    if len(live) > 1:
        eid, _ = live[0]
        g.world.destroy_entity(eid)
    assert g._maybe_exit_cleared_arena() is False
    assert g.level is not None


@pytest.mark.asyncio
async def test_non_arena_level_never_auto_exits(tmp_path) -> None:
    """A regular dungeon level with no live AI (e.g. an empty
    corridor section in a still-loading floor) must not trigger
    the auto-exit -- that path is arena-only."""
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    # Hand-make a non-arena level with no foes.
    from nhc.dungeon.model import Level, Terrain, Tile
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(5)]
        for _ in range(5)
    ]
    g.level = Level(
        id="dummy", name="dummy", depth=1,
        width=5, height=5, tiles=tiles,
    )
    assert g._maybe_exit_cleared_arena() is False
    assert g.level is not None

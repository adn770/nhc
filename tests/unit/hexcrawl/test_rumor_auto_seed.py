"""Auto-seed the rumor pool on settlement entry.

Without this hook the innkeeper bump always answers
"rumor.none" -- the data layer ships rumors but nobody is
populating :attr:`HexWorld.active_rumors` at runtime. On first
entry to a settlement hex the game now seeds a small pool so
the innkeeper can actually talk. God-mode sessions get the
truthful generator so the debug player never chases a false
lead.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import GameMode
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


def _make_hex_game(tmp_path, *, god: bool = False) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
        god_mode=god,
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
# First-entry behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_seeds_rumors_when_pool_empty(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    assert g.hex_world.active_rumors == []
    _seed_settlement(g)
    await g.enter_hex_feature()
    assert g.hex_world.active_rumors, (
        "town entry with an empty pool must seed fresh rumors"
    )


@pytest.mark.asyncio
async def test_entry_keeps_existing_rumors(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    preset = [
        Rumor(id="preset", text="rumor.true_feature", truth=True),
    ]
    g.hex_world.active_rumors = list(preset)
    _seed_settlement(g)
    await g.enter_hex_feature()
    # Pool wasn't empty, so the auto-seed is a no-op.
    assert g.hex_world.active_rumors == preset


@pytest.mark.asyncio
async def test_cave_entry_does_not_seed(tmp_path) -> None:
    """The auto-seed is settlement-only -- a cave entry leaves
    the rumor pool untouched."""
    g = _make_hex_game(tmp_path)
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.CAVE
    cell.dungeon = DungeonRef(template="procedural:cave")
    await g.enter_hex_feature()
    assert g.hex_world.active_rumors == []


# ---------------------------------------------------------------------------
# God mode uses the truthful generator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_god_mode_seeds_only_truthful_rumors(tmp_path) -> None:
    g = _make_hex_game(tmp_path, god=True)
    _seed_settlement(g)
    await g.enter_hex_feature()
    assert g.hex_world.active_rumors
    assert all(r.truth for r in g.hex_world.active_rumors), (
        "god mode must flip every seeded rumor to truth=True"
    )

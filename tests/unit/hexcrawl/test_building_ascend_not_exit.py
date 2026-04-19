"""Pressing ``<`` on a building-interior ``stairs_up`` tile must
go up a floor, not back to the overland hex flower.

An earlier hex-mode intercept in ``Game._get_classic_actions``
routed *any* ``ascend`` input on a depth <= 1 ``stairs_up`` tile
straight to ``exit_dungeon_to_hex``. That was correct for the old
Settlement generator (where ground-floor stairs_up was the
overland exit) but wrong after the split to the Site model --
building floors now use ``stairs_up`` for the cross-floor stair
physically leading up a storey, and ground-floor dungeon ``<``
is the real overland exit.

The intercept must therefore fire only on plain dungeon levels
(``level.building_id is None``); building interiors fall through
to ``AscendStairsAction`` which already handles the depth + 1
cache mapping.
"""

from __future__ import annotations

import pytest

from nhc.core.events import LevelEntered
from nhc.core.game import Game
from nhc.dungeon.model import Level, LevelMetadata, Terrain, Tile
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.mode import Difficulty, WorldType
from nhc.i18n import init as i18n_init


class _ScriptedClient:
    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __init__(self, script: list[tuple[str, object]]) -> None:
        self._script = list(script)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync

    async def get_input(self):
        if self._script:
            return self._script.pop(0)
        return ("disconnect", None)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(tmp_path, script):
    g = Game(
        client=_ScriptedClient(script),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL,
        difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _install_building_ground_floor(g: Game) -> Level:
    """Swap a hand-built building ground floor into the game
    with the player standing on a stairs_up tile."""
    level = Level.create_empty("bld_f0", "ground", 1, 5, 5)
    level.metadata = LevelMetadata(theme="dungeon")
    level.building_id = "b0"
    level.floor_index = 0
    for y in range(level.height):
        for x in range(level.width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[2][2] = Tile(
        terrain=Terrain.FLOOR, feature="stairs_up",
    )
    g.level = level
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = 2, 2
    pos.level_id = level.id
    return level


@pytest.mark.asyncio
async def test_ascend_in_building_does_not_exit_to_overland(
    tmp_path,
) -> None:
    g = _make_game(tmp_path, [("ascend", None)])
    level = _install_building_ground_floor(g)

    exited = False

    async def _fail_exit():
        nonlocal exited
        exited = True
        return True

    g.exit_dungeon_to_hex = _fail_exit  # type: ignore[assignment]

    actions = await g._get_classic_actions()

    assert not exited, (
        "building-interior ascend must not route through "
        "exit_dungeon_to_hex -- that is the leftover "
        "Settlement-generator behaviour the fix targets"
    )
    assert g.level is level, (
        "the building floor must still be the current level"
    )
    assert actions and len(actions) == 1, (
        "an AscendStairsAction should be dispatched instead"
    )


@pytest.mark.asyncio
async def test_ascend_on_plain_dungeon_stairs_up_still_exits(
    tmp_path,
) -> None:
    """Regression for the other direction: a plain dungeon level
    (building_id is None) at depth 1 with stairs_up must still
    pop back to the hex overland -- that is the supported
    ground-floor-dungeon exit path."""
    g = _make_game(tmp_path, [("ascend", None)])
    level = Level.create_empty("cave_1", "cave", 1, 5, 5)
    level.metadata = LevelMetadata(theme="dungeon")
    for y in range(level.height):
        for x in range(level.width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[2][2] = Tile(
        terrain=Terrain.FLOOR, feature="stairs_up",
    )
    g.level = level
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = 2, 2
    pos.level_id = level.id

    called = False

    async def _exit_ok():
        nonlocal called
        called = True
        return True

    g.exit_dungeon_to_hex = _exit_ok  # type: ignore[assignment]

    actions = await g._get_classic_actions()

    assert called, (
        "plain dungeon ground-floor stairs_up must still route "
        "to the overland via exit_dungeon_to_hex"
    )
    assert actions == []

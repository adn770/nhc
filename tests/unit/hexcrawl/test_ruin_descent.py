"""Ruin descent wiring (milestone 7).

A ruin's mandatory 3-floor descent must be reachable end-to-end:
descend 1 -> 2 -> 3, ascend back, re-entry returns cached floors.
Every descent floor generates via the ``procedural:ruin``
template (not the generic depth-themed pipeline).
"""

from __future__ import annotations

import asyncio

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import (
    Biome, DungeonRef, HexCell, HexFeatureType, HexWorld,
)
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
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(), backend=None,
        game_mode="classic",
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path, seed=42,
    )
    g.initialize()
    return g


def _seed_ruin(g: Game) -> HexCell:
    g.hex_world = HexWorld(
        pack_id="t", seed=42, width=1, height=1,
    )
    cell = HexCell(
        coord=HexCoord(0, 0), biome=Biome.FOREST,
        feature=HexFeatureType.RUIN,
        dungeon=DungeonRef(
            template="procedural:ruin",
            site_kind="ruin",
            faction="goblin",
        ),
    )
    g.hex_world.set_cell(cell)
    g.hex_world.visit(cell.coord)
    g.hex_player_position = cell.coord
    return cell


async def _enter_building_ground(g: Game) -> None:
    """Park the player on the ruin building's ground floor with
    the descent stair tile under them."""
    cell = _seed_ruin(g)
    await g._enter_walled_site(cell.coord, "ruin")
    # Step into the building: swap level to the building ground.
    assert g._active_site is not None
    building = g._active_site.buildings[0]
    g.level = building.ground
    # Find the descent stair tile and place the player there.
    stair_xy = next(
        (x, y)
        for y in range(building.ground.height)
        for x in range(building.ground.width)
        if building.ground.tiles[y][x].feature == "stairs_down"
    )
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = stair_xy
    pos.level_id = building.ground.id


def _player_descend(g: Game) -> None:
    """Fire a LevelEntered event for the current descent direction."""
    from nhc.core.events import LevelEntered
    new_depth = g.level.depth + 1
    g._on_level_entered(LevelEntered(depth=new_depth))


def _player_ascend(g: Game) -> None:
    from nhc.core.events import LevelEntered
    new_depth = g.level.depth - 1
    g._on_level_entered(LevelEntered(depth=new_depth))


# ---------------------------------------------------------------------------
# Descent traversal
# ---------------------------------------------------------------------------


def test_descend_from_ruin_building_enters_descent_floor_1(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)
        assert g._active_descent_building is not None
        assert g.level.depth == 2

    asyncio.run(_run())


def test_descent_floor_1_uses_procedural_ruin_template(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)
        assert g.generation_params is not None
        assert g.generation_params.template == "procedural:ruin"

    asyncio.run(_run())


def test_descend_from_floor_1_reaches_floor_2(tmp_path) -> None:
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)  # ground -> floor 1 (depth 2)
        _player_descend(g)  # floor 1 -> floor 2 (depth 3)
        assert g.level.depth == 3
        assert g.generation_params.template == "procedural:ruin"

    asyncio.run(_run())


def test_descend_from_floor_2_reaches_floor_3(tmp_path) -> None:
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)  # -> depth 2
        _player_descend(g)  # -> depth 3
        _player_descend(g)  # -> depth 4 (floor 3)
        assert g.level.depth == 4
        assert g.generation_params.template == "procedural:ruin"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Ascent
# ---------------------------------------------------------------------------


def test_ascend_from_floor_3_returns_to_floor_2(tmp_path) -> None:
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        for _ in range(3):
            _player_descend(g)
        assert g.level.depth == 4
        _player_ascend(g)
        assert g.level.depth == 3

    asyncio.run(_run())


def test_ascend_from_floor_1_returns_to_building_ground(
    tmp_path,
) -> None:
    """Ascending from descent Floor 1 (depth 2) must land the
    player back on the ruin building's ground floor -- same
    pattern tower / keep / mansion cellars already use."""
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)
        assert g.level.depth == 2
        _player_ascend(g)
        assert g.level.depth == 1
        assert g.level.building_id is not None
        assert g._active_descent_building is None

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_ruin_descent_cached_on_re_entry(tmp_path) -> None:
    """Going down twice -> up twice -> down twice must return the
    same Level instance from the floor cache on the second
    descent."""
    g = _make_game(tmp_path)

    async def _run() -> None:
        await _enter_building_ground(g)
        _player_descend(g)
        depth_2_level = g.level
        _player_descend(g)
        depth_3_level = g.level
        _player_ascend(g)  # to depth 2
        assert g.level is depth_2_level
        _player_descend(g)  # back to depth 3
        assert g.level is depth_3_level

    asyncio.run(_run())

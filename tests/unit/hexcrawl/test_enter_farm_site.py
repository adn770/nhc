"""Farm site routing through enter_hex_feature.

FARM is promoted from a sub-hex minor feature to a first-class
:class:`HexFeatureType` so the building-generator's farm
assembler can drive it end-to-end. A hex tagged
``HexFeatureType.FARM`` with ``DungeonRef.site_kind == "farm"``
dispatches through :func:`assemble_site` and lands the player on
the farmhouse's ground floor.  Minor-feature FARM dressing (the
sub-hex roadside farmstead find) is unrelated to this routing.
"""

from __future__ import annotations

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


def _make_game(tmp_path, mode: GameMode = GameMode.HEX_EASY) -> Game:
    from tests.unit.hexcrawl.test_enter_exit import _make_game as mk
    return mk(tmp_path, mode)


def _attach_farm_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.FARM
    cell.dungeon = DungeonRef(
        template="procedural:farm",
        depth=1,
        site_kind="farm",
    )
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_farm_site_kind_assembles_farmhouse_level(
    tmp_path,
) -> None:
    """The active level is the farmhouse's ground floor."""
    g = _make_game(tmp_path)
    _attach_farm_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.building_id is not None
    assert g.level.building_id.endswith("_farmhouse")
    assert g.level.floor_index == 0


@pytest.mark.asyncio
async def test_farm_site_kind_caches_level(tmp_path) -> None:
    """Re-entering the same farm hex reuses the cached level."""
    g = _make_game(tmp_path)
    _attach_farm_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    await g.enter_hex_feature()
    assert g.level is level_first


@pytest.mark.asyncio
async def test_farm_site_places_player_on_entry(tmp_path) -> None:
    """Player lands on a floor tile on the farmhouse ground floor."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_farm_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR


def test_farm_is_hex_feature_type() -> None:
    """FARM is exposed as a major hex feature."""
    assert HexFeatureType.FARM.value == "farm"

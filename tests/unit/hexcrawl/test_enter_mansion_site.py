"""Mansion site routing through enter_hex_feature.

When a hex feature's DungeonRef carries site_kind = "mansion",
the game engine dispatches through assemble_site() and lands the
player on the ground floor of the first building in the assembled
mansion Site.  Mirrors the tower wiring; cross-building
navigation is a follow-up and out of scope for this round of
tests.
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


def _attach_mansion_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.MANSION
    cell.dungeon = DungeonRef(
        template="procedural:mansion",
        depth=1,
        site_kind="mansion",
    )
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_mansion_site_kind_assembles_building_level(
    tmp_path,
) -> None:
    """The active level is the first mansion building's ground floor."""
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.building_id is not None
    assert g.level.building_id.endswith("_b0")
    assert g.level.floor_index == 0


@pytest.mark.asyncio
async def test_mansion_site_kind_caches_level(tmp_path) -> None:
    """Re-entering the same mansion hex reuses the cached level."""
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    await g.enter_hex_feature()
    assert g.level is level_first


@pytest.mark.asyncio
async def test_mansion_site_places_player_on_entry(tmp_path) -> None:
    """Player lands on a floor tile on the mansion ground floor."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR


@pytest.mark.asyncio
async def test_mansion_caches_all_buildings_ground_floors(
    tmp_path,
) -> None:
    """Every mansion building's floors land in the floor cache.

    Mansions have 2-4 buildings of 1-2 floors each. Every floor
    should be cached so any future door-based transition can find
    the target level without re-running the assembler.
    """
    g = _make_game(tmp_path)
    _attach_mansion_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    cache = g._floor_cache
    # Ground level (depth 1) is always cached.
    assert g._cache_key(1) in cache
    # At least one other cache entry for an adjacent building or a
    # higher floor.
    extra_keys = [k for k in cache if k != g._cache_key(1)]
    assert extra_keys, "expected more than just the ground cache slot"
    # Every cached Level must carry the back-reference set by the
    # assembler.
    for _, (level, _) in cache.items():
        assert level.building_id is not None
        assert level.floor_index is not None

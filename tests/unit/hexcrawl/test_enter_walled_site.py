"""Keep and town site routing through enter_hex_feature.

Walled sites (keep with fortification, town with palisade) share
an entry pattern: the player lands on the Site's ``surface``
Level -- the courtyard or street between buildings -- rather than
inside any one building. Cross-building navigation (walking up to
a door_closed tile and entering the building behind it) is out of
scope for this wiring and tracked separately.
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


def _attach_keep_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.KEEP
    cell.dungeon = DungeonRef(
        template="procedural:keep",
        depth=1,
        site_kind="keep",
    )
    g.hex_player_position = coord


def _attach_town_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.VILLAGE
    cell.dungeon = DungeonRef(
        template="procedural:settlement",
        depth=1,
        site_kind="town",
        size_class="village",
    )
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_keep_site_kind_lands_player_on_surface(
    tmp_path,
) -> None:
    """The active level is the keep's courtyard surface, not a
    building floor."""
    from nhc.dungeon.model import SurfaceType, Terrain
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    # Surface levels don't carry a building_id (they're not a
    # building floor); their floor tiles have SurfaceType.STREET.
    assert g.level.building_id is None
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR
    assert tile.surface_type == SurfaceType.STREET


@pytest.mark.asyncio
async def test_keep_site_caches_all_buildings(tmp_path) -> None:
    """Every keep building lands in the floor cache."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    # Cache should carry keep-keyed entries for every building.
    keep_keys = [
        k for k in g._floor_cache
        if isinstance(k, tuple) and len(k) == 5 and k[0] == "keep"
    ]
    assert keep_keys, "expected keep-specific cache entries"


@pytest.mark.asyncio
async def test_keep_site_caches_level_on_re_entry(tmp_path) -> None:
    """Re-entering the same keep hex reuses the cached surface."""
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    await g.enter_hex_feature()
    assert g.level is level_first


@pytest.mark.asyncio
async def test_town_site_kind_lands_player_on_street(
    tmp_path,
) -> None:
    """The active level is the town's street surface."""
    from nhc.dungeon.model import SurfaceType, Terrain
    g = _make_game(tmp_path)
    _attach_town_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.level.building_id is None
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR
    assert tile.surface_type == SurfaceType.STREET


@pytest.mark.asyncio
async def test_town_site_caches_all_buildings(tmp_path) -> None:
    """Every town building lands in the floor cache."""
    g = _make_game(tmp_path)
    _attach_town_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    town_keys = [
        k for k in g._floor_cache
        if isinstance(k, tuple) and len(k) == 5 and k[0] == "town"
    ]
    assert town_keys, "expected town-specific cache entries"

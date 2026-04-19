"""Settlement entry / exit wiring (M-2.2).

Game.enter_hex_feature routes settlement hexes (DungeonRef
template starting with ``procedural:settlement``) through the
town generator from M-2.1 instead of the BSP cave / ruin
pipeline. Exit uses the same ExitDungeonAction-style path.
"""

from __future__ import annotations

import pytest

from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import Difficulty, WorldType, GameMode
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


def _make_hex_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _settle_hub(g: Game) -> HexCoord:
    """Ensure the player stands on the hub and it has a town
    DungeonRef (the generator seeds this, but this helper is
    robust to older setups)."""
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    if cell.feature is HexFeatureType.NONE:
        cell.feature = HexFeatureType.CITY
    cell.dungeon = DungeonRef(template="procedural:settlement")
    return coord


# ---------------------------------------------------------------------------
# Entry loads the town level
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_settlement_loads_town_map(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    assert g.level is None
    ok = await g.enter_hex_feature()
    assert ok
    assert g.level is not None
    # Town signature: lands the player on the town site's
    # surface level (street grid) and parks the Site on
    # _active_site for the door-crossing handler.
    assert g._active_site is not None
    assert g._active_site.kind == "town"
    # The service-role buildings get their role tags on the
    # ground-floor Room so downstream systems can find them.
    all_tags = {
        t for b in g._active_site.buildings
        for t in b.ground.rooms[0].tags
    }
    # At minimum the three NPC-bearing roles are always present.
    for required in ("shop", "inn", "temple"):
        assert required in all_tags, (required, all_tags)


@pytest.mark.asyncio
async def test_enter_settlement_is_seed_reproducible(tmp_path) -> None:
    g1 = _make_hex_game(tmp_path)
    _settle_hub(g1)
    await g1.enter_hex_feature()
    layout1 = [(r.id, tuple(r.tags), r.rect.x, r.rect.y) for r in g1.level.rooms]

    g2 = _make_hex_game(tmp_path / "sub2")
    _settle_hub(g2)
    await g2.enter_hex_feature()
    layout2 = [(r.id, tuple(r.tags), r.rect.x, r.rect.y) for r in g2.level.rooms]

    assert layout1 == layout2


@pytest.mark.asyncio
async def test_enter_settlement_places_player_on_street(tmp_path) -> None:
    """Town sites land the player on a walkable STREET tile near
    the first palisade gate -- there is no stairs_up tile on the
    site surface."""
    from nhc.dungeon.model import SurfaceType, Terrain

    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR
    assert tile.surface_type == SurfaceType.STREET


# ---------------------------------------------------------------------------
# Exit and re-entry round trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exit_settlement_pops_back_to_overland(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    assert g.level is not None
    ok = await g.exit_dungeon_to_hex()
    assert ok
    assert g.level is None
    # Hex state preserved.
    assert g.hex_world is not None
    assert g.hex_player_position is not None


@pytest.mark.asyncio
async def test_enter_settlement_reuses_floor_cache(tmp_path) -> None:
    g = _make_hex_game(tmp_path)
    _settle_hub(g)
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    # Re-entering the same hex at depth 1 should hand back the
    # cached Level instance, not regenerate.
    await g.enter_hex_feature()
    assert g.level is level_first

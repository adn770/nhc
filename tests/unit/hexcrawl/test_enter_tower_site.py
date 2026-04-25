"""Tower site routing through enter_hex_feature.

When a hex feature's DungeonRef carries site_kind = "tower", the
game engine dispatches through assemble_site() and lands the
player on the ground floor of the assembled tower Building
instead of running the old procedural:tower template. Other
site_kind values still flow through the template pipeline; this
is the first live-routed kind.
"""

from __future__ import annotations

import pytest

from nhc.core.autosave import has_autosave
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


def _attach_tower_site(g: Game, coord: HexCoord) -> None:
    cell = g.hex_world.cells[coord]
    cell.feature = HexFeatureType.TOWER
    cell.dungeon = DungeonRef(
        template="procedural:tower",
        depth=1,
        site_kind="tower",
    )
    g.hex_player_position = coord


@pytest.mark.asyncio
async def test_tower_site_kind_assembles_building_level(tmp_path) -> None:
    """The active level is the assembled tower's ground floor."""
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    # Ground-floor Level carries the building back-reference set
    # by the tower assembler.
    assert g.level.building_id is not None
    assert g.level.building_id.endswith("_tower")
    assert g.level.floor_index == 0


@pytest.mark.asyncio
async def test_tower_site_kind_caches_level(tmp_path) -> None:
    """Re-entering the same tower hex reuses the cached level."""
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level_first = g.level
    await g.exit_dungeon_to_hex()
    await g.enter_hex_feature()
    assert g.level is level_first


@pytest.mark.asyncio
async def test_tower_site_places_player_on_entry(tmp_path) -> None:
    """Player lands on a floor tile on the tower's ground floor."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    pos = g.world.get_component(g.player_id, "Position")
    assert pos is not None
    tile = g.level.tile_at(pos.x, pos.y)
    assert tile is not None
    assert tile.terrain == Terrain.FLOOR


@pytest.mark.asyncio
async def test_bare_dungeonref_without_site_kind_uses_old_path(
    tmp_path,
) -> None:
    """Without site_kind, a tower hex still uses the template path."""
    g = _make_game(tmp_path)
    cell = g.hex_world.cells[HexCoord(0, 0)]
    cell.feature = HexFeatureType.TOWER
    cell.dungeon = DungeonRef(
        template="procedural:tower", depth=1,
    )  # NOTE: no site_kind
    g.hex_player_position = HexCoord(0, 0)
    await g.enter_hex_feature()
    # Old path stamps generation_params; the new site path leaves
    # generation_params untouched from a previous entry (likely None
    # on a fresh game).
    assert g.generation_params is not None
    assert g.generation_params.template == "procedural:tower"


@pytest.mark.asyncio
async def test_unknown_site_kind_falls_through_to_template(
    tmp_path,
) -> None:
    """Only the known site_kinds route through the new path; any
    other value falls through to the template pipeline."""
    g = _make_game(tmp_path)
    cell = g.hex_world.cells[HexCoord(0, 0)]
    cell.feature = HexFeatureType.KEEP
    cell.dungeon = DungeonRef(
        template="procedural:keep",
        depth=1,
        site_kind="somewhere_not_wired",
    )
    g.hex_player_position = HexCoord(0, 0)
    await g.enter_hex_feature()
    assert g.level is not None
    assert g.generation_params is not None
    assert g.generation_params.template == "procedural:keep"


@pytest.mark.asyncio
async def test_tower_caches_every_floor_by_depth(tmp_path) -> None:
    """All tower floors land somewhere addressable so the engine's
    existing descend / ascend transition finds them.

    M6d-3 split: the ground floor (= site surface for a
    single-building tower) lives on :class:`SiteCacheManager`;
    upper floors stay on the legacy ``_floor_cache`` under the
    depth-keyed ``(q, r, depth)`` shape.
    """
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    assert g.level is not None
    # Active level is depth=1 (ground). Tower towers have 2-6
    # floors; ground sits in the manager, every upper floor in
    # _floor_cache.
    ground_key = g._cache_key(1)
    assert ground_key[0] == "site"
    assert g._site_cache_manager is not None
    assert g._site_cache_manager.has(ground_key)
    assert ground_key not in g._floor_cache, (
        "tower ground belongs on the manager, not _floor_cache"
    )
    # At least one upper floor is present in the legacy cache.
    higher_keys = list(g._floor_cache.keys())
    assert higher_keys, "expected upper floors cached"


@pytest.mark.asyncio
async def test_tower_cached_upper_floor_has_floor_index(
    tmp_path,
) -> None:
    """Cached upper floors still carry the Building back-reference."""
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    for key, (level, _) in g._floor_cache.items():
        if level is g.level:
            continue
        assert level.building_id is not None
        assert level.floor_index is not None
        assert level.floor_index >= 1

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


class _RecordingClient:
    """Fake client that records every send_floor_change call and
    pretends to render a unique SVG string per Level id so
    ``_svg_cache`` actually ends up storing string values (instead
    of the __getattr__ lambdas of the bare _FakeClient).
    """

    game_mode = "classic"
    lang = "en"
    edge_doors = False

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.floor_svg: str = ""
        self.floor_svg_id: str = ""
        self.calls: list[dict] = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def _sync(*a, **kw):
            return None

        return _sync

    def send_floor_change(
        self, level, world, player_id, turn, *,
        seed=0, floor_svg=None, floor_svg_id=None,
        hatch_distance=2.0, site=None,
    ) -> None:
        if floor_svg and floor_svg_id:
            self.floor_svg = floor_svg
            self.floor_svg_id = floor_svg_id
            cache_hit = True
        else:
            # Pretend to render a Level-specific SVG with the
            # Level's id woven into the body so a collision is
            # detectable by inspecting floor_svg.
            self.floor_svg = f"<svg data-level='{level.id}'/>"
            self.floor_svg_id = f"id-{level.id}"
            cache_hit = False
        self.calls.append({
            "level_id": level.id,
            "depth": level.depth,
            "cache_hit": cache_hit,
            "floor_svg_id": self.floor_svg_id,
        })


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


@pytest.mark.asyncio
async def test_town_entry_pre_reveals_non_void_tiles(tmp_path) -> None:
    """Entering a town marks every non-VOID surface tile as explored,
    so the client can draw the whole layout without fog of war. Visible
    marking stays tied to the player's FOV -- explored is the only bit
    we're short-cutting."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_town_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level = g.level
    assert level is not None and level.metadata.prerevealed is True
    total = 0
    explored = 0
    for row in level.tiles:
        for t in row:
            if t.terrain == Terrain.VOID:
                continue
            total += 1
            if t.explored:
                explored += 1
    assert total > 0, "expected some walkable tiles on town surface"
    assert explored == total, (
        f"every non-VOID tile should be explored, got {explored}/{total}"
    )


@pytest.mark.asyncio
async def test_town_entry_does_not_over_mark_visible(tmp_path) -> None:
    """Prereveal only touches the ``explored`` bit. ``visible`` stays
    tied to the player's FOV radius; otherwise entities sprinkled
    across the town would render without their discovery loop."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_town_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level = g.level
    assert level is not None
    visible_count = sum(
        1 for row in level.tiles for t in row
        if t.visible and t.terrain != Terrain.VOID
    )
    non_void_count = sum(
        1 for row in level.tiles for t in row
        if t.terrain != Terrain.VOID
    )
    # A tight FOV on a big street grid never lights up the full
    # surface on turn 1.
    assert visible_count < non_void_count, (
        "prereveal must not flip every tile to visible; that would "
        "expose entities outside the player's FOV"
    )


@pytest.mark.asyncio
async def test_keep_entry_pre_reveals_non_void_tiles(tmp_path) -> None:
    """Same rule for the keep courtyard -- walled-site entry flags
    prereveal uniformly, regardless of faction (Q2=a)."""
    from nhc.dungeon.model import Terrain
    g = _make_game(tmp_path)
    _attach_keep_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    level = g.level
    assert level is not None and level.metadata.prerevealed is True
    total = explored = 0
    for row in level.tiles:
        for t in row:
            if t.terrain == Terrain.VOID:
                continue
            total += 1
            if t.explored:
                explored += 1
    assert total > 0
    assert explored == total


@pytest.mark.asyncio
async def test_svg_cache_keyed_by_level_id_not_depth(tmp_path) -> None:
    """Regression: an earlier `_svg_cache` was keyed by depth,
    which collided when the town surface (depth=0 via
    Level.create_empty but passed as 1 to _notify_floor_change) and
    a building ground floor (depth=1 by construction) both landed
    in the same slot. The building interior was served the cached
    town-surface SVG as a result. Keying by level.id avoids the
    collision."""
    g = _make_game(tmp_path)
    g.renderer = _RecordingClient()
    _attach_town_site(g, HexCoord(0, 0))
    await g.enter_hex_feature()
    surface_level = g.level
    assert surface_level is not None
    assert g.renderer.floor_svg.endswith(f"data-level='{surface_level.id}'/>")
    # Cache must be keyed by level.id, not a depth integer.
    assert surface_level.id in g._svg_cache
    assert all(
        isinstance(k, str) for k in g._svg_cache.keys()
    ), f"_svg_cache keys must be strings, got {list(g._svg_cache)}"

    # Swap into one of the buildings (ground floor). Pick any
    # walkable tile from the ground floor to seed the position.
    from nhc.dungeon.model import Terrain
    assert g._active_site is not None
    building = g._active_site.buildings[0]
    bx = by = 1
    for y, row in enumerate(building.ground.tiles):
        for x, tile in enumerate(row):
            if tile.terrain == Terrain.FLOOR:
                bx, by = x, y
                break
        if (bx, by) != (1, 1):
            break
    g._swap_to_building(building, bx, by)
    # After swap, the recorder should NOT have served the cached
    # surface SVG for the building interior. Either it's a miss
    # and rendered fresh, or it has the building's own Level id
    # stitched in (our _RecordingClient proves this via the body).
    interior_level = g.level
    assert interior_level is not None
    assert interior_level.id != surface_level.id
    assert g.renderer.floor_svg_id != f"id-{surface_level.id}", (
        "building interior must not reuse the surface SVG cache slot"
    )
    assert (
        f"data-level='{interior_level.id}'"
        in g.renderer.floor_svg
    ), (
        "floor_svg body must reflect the new (interior) Level's id"
    )


@pytest.mark.asyncio
async def test_keep_surface_lives_on_site_cache_manager(tmp_path) -> None:
    """The macro keep surface lands on :class:`SiteCacheManager`
    rather than the legacy ``_floor_cache``. M6d-3 invariant: every
    site surface (macro and sub-hex) shares the LRU + on-disk
    mutation pipeline."""
    g = _make_game(tmp_path)
    coord = HexCoord(0, 0)
    _attach_keep_site(g, coord)
    await g.enter_hex_feature()
    surface_key = ("site", coord.q, coord.r, 1)
    assert g._site_cache_manager is not None
    assert g._site_cache_manager.has(surface_key)
    assert surface_key not in g._floor_cache, (
        "keep surface should live on SiteCacheManager only; the "
        "legacy floor cache slot must stay free of the surface"
    )


@pytest.mark.asyncio
async def test_keep_surface_door_mutation_replays_after_eviction(
    tmp_path,
) -> None:
    """A door-open mutation on a macro keep surface persists across
    LRU eviction. Pre-M6d-3 the macro surface lived on
    ``_floor_cache`` (no mutation persistence) so this round-trip
    reset the door to ``door_closed``; M6d-3 folds the macro
    surface onto :class:`SiteCacheManager` so every site -- macro
    and sub-hex -- shares the LRU + on-disk mutation replay path."""
    from nhc.core.site_cache import SiteCacheManager
    g = _make_game(tmp_path)
    coord_a = HexCoord(0, 0)
    coord_b = HexCoord(2, 0)
    _attach_keep_site(g, coord_a)
    await g.enter_hex_feature()

    surface_key = ("site", coord_a.q, coord_a.r, 1)
    assert g._site_cache_manager is not None
    assert g._site_cache_manager.has(surface_key)

    surface = g.level
    tile = surface.tile_at(3, 3)
    tile.feature = "door_closed"
    g._set_sub_hex_mutation("doors", "3,3", "open")

    # Force eviction by replacing manager with a 1-slot version
    # that preserves the just-recorded mutation on coord_a.
    new_mgr = SiteCacheManager(
        capacity=1, storage_dir=tmp_path, player_id="game",
    )
    for k, v in g._site_cache_manager._entries.items():
        new_mgr.store(k, v["level"], mutations=v["mutations"])
    g._site_cache_manager = new_mgr

    # Exit the keep, then enter a different keep so coord_a evicts
    # to disk (capacity=1).
    await g.exit_dungeon_to_hex()
    _attach_keep_site(g, coord_b)
    await g.enter_hex_feature()

    # Re-enter the original keep; cache miss, fresh assemble, then
    # the persisted mutation replays.
    await g.exit_dungeon_to_hex()
    _attach_keep_site(g, coord_a)
    await g.enter_hex_feature()

    assert g.level is not surface, (
        "post-eviction re-entry should produce a freshly "
        "assembled surface"
    )
    assert g.level.tile_at(3, 3).feature == "door_open", (
        "the door-open mutation must replay after eviction"
    )

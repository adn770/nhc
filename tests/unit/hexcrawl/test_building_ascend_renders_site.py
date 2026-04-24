"""Ascend / descend between building floors must pass the active
Site through to ``send_floor_change`` so the renderer picks the
building path and draws interior edge walls.

Regression: on a mid-session ascent the caller dropped the
``site=`` kwarg, so ``render_level_svg`` fell back to the plain
dungeon renderer and no interior-wall <line> elements were
emitted on the upper floor.
"""

from __future__ import annotations

import pytest

from nhc.core.events import LevelEntered
from nhc.core.game import Game
from nhc.dungeon.building import Building, StairLink
from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, RectShape, Terrain, Tile,
)
from nhc.sites._site import Site
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import Difficulty, WorldType
from nhc.i18n import init as i18n_init


class _SpyClient:
    """Minimal WebClient stub that records send_floor_change kwargs."""

    game_mode = "classic"
    lang = "en"
    edge_doors = False
    messages: list[str] = []

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.floor_svg = ""
        self.floor_svg_id = ""

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
        self.calls.append({
            "level_id": level.id,
            "site": site,
            "building_id": getattr(level, "building_id", None),
            "floor_index": getattr(level, "floor_index", None),
        })


@pytest.fixture(scope="module", autouse=True)
def _bootstrap() -> None:
    i18n_init("en")
    EntityRegistry.discover_all()


def _mk_floor(
    fid: str, depth: int, floor_index: int,
    up_tile: tuple[int, int] | None = None,
    down_tile: tuple[int, int] | None = None,
) -> Level:
    level = Level.create_empty(fid, f"floor{depth}", depth, 7, 7)
    level.metadata = LevelMetadata(theme="dungeon")
    level.building_id = "b0"
    level.floor_index = floor_index
    for y in range(level.height):
        for x in range(level.width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    if up_tile is not None:
        ux, uy = up_tile
        level.tiles[uy][ux] = Tile(
            terrain=Terrain.FLOOR, feature="stairs_up",
        )
    if down_tile is not None:
        dx, dy = down_tile
        level.tiles[dy][dx] = Tile(
            terrain=Terrain.FLOOR, feature="stairs_down",
        )
    return level


def _install_site(g: Game) -> Site:
    from_tile = (2, 3)
    to_tile = (4, 1)
    ground = _mk_floor(
        "b_f0", depth=1, floor_index=0, up_tile=from_tile,
    )
    upper = _mk_floor(
        "b_f1", depth=2, floor_index=1, down_tile=to_tile,
    )
    # Upper floor has an interior edge wall that should be drawn.
    upper.interior_edges = {(3, 3, "north")}
    building = Building(
        id="b0",
        base_shape=RectShape(),
        base_rect=Rect(x=0, y=0, width=7, height=7),
        floors=[ground, upper],
        stair_links=[
            StairLink(
                from_floor=0, to_floor=1,
                from_tile=from_tile, to_tile=to_tile,
            ),
        ],
    )
    site = Site(
        id="site_0_0",
        kind="tower",
        buildings=[building],
        surface=Level.create_empty("surf", "surf", 1, 20, 20),
    )
    g._active_site = site
    g.hex_player_position = HexCoord(0, 0)
    g._floor_cache[g._cache_key(1)] = (ground, {})
    g._floor_cache[g._cache_key(2)] = (upper, {})
    g.level = ground
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = from_tile
    pos.level_id = ground.id
    return site


def test_ascend_passes_site_to_send_floor_change(tmp_path) -> None:
    spy = _SpyClient()
    g = Game(
        client=spy, backend=None, style="classic",
        world_type=WorldType.HEXCRAWL, difficulty=Difficulty.EASY,
        save_dir=tmp_path, seed=42,
    )
    g.initialize()
    site = _install_site(g)

    g._on_level_entered(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))

    # The ascent handler should have called send_floor_change once
    # with the active site so the renderer picks the building path
    # and emits interior edge walls on the upper floor.
    assert spy.calls, "send_floor_change was never called"
    last = spy.calls[-1]
    assert last["building_id"] == "b0"
    assert last["floor_index"] == 1
    assert last["site"] is site, (
        "ascent must pass the active Site to send_floor_change, "
        "otherwise render_level_svg drops to the plain dungeon "
        "renderer and interior edge walls disappear from the "
        "upper floor"
    )

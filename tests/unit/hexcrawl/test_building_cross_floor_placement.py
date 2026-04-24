"""Stair placement between building floors must land on the
matching stair tile, not the generic room-center fallback.

Building stair actions flip the depth direction so floor_index
grows with depth inside the building (ground=depth1, upper
floors=depth2+). The game's ``_on_level_entered`` used to pick
the destination stair feature from ``ascending = new < old``,
which is *inverted* for building floors: pressing ``<`` on the
ground floor sends ``new_depth > old_depth``, so the logic
looked for ``stairs_up`` on the upper floor and found nothing,
dropping the player at the entry-room center.

The fix consults the building's ``stair_links`` to place the
player at the link's target tile -- the exact counterpart of
the stair they just used. These tests lock that invariant.
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


def _make_game(tmp_path) -> Game:
    g = Game(
        client=_FakeClient(),
        backend=None,
        style="classic",
        world_type=WorldType.HEXCRAWL,
        difficulty=Difficulty.EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


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


def _install_two_floor_building(g: Game) -> tuple[Building, tuple, tuple]:
    """Build a 2-floor building with one cross-floor stair link,
    install both floors in the floor cache, and return the
    building plus the link's (from_tile, to_tile)."""
    from_tile = (2, 3)
    to_tile = (4, 1)
    ground = _mk_floor("b_f0", depth=1, floor_index=0, up_tile=from_tile)
    upper = _mk_floor("b_f1", depth=2, floor_index=1, down_tile=to_tile)
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
    return building, from_tile, to_tile


def test_ascend_ground_to_upper_lands_on_paired_stair(tmp_path) -> None:
    g = _make_game(tmp_path)
    _, from_tile, to_tile = _install_two_floor_building(g)

    # Emit what AscendStairsAction emits on a building floor.
    g._on_level_entered(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))

    assert g.level.floor_index == 1
    pos = g.world.get_component(g.player_id, "Position")
    assert (pos.x, pos.y) == to_tile, (
        "ascending from ground floor must place the player on the "
        "upper floor's stairs_down tile (the cross-floor link's "
        f"to_tile {to_tile}), not on the room-center fallback"
    )


def test_descend_upper_to_ground_lands_on_paired_stair(tmp_path) -> None:
    g = _make_game(tmp_path)
    _, from_tile, to_tile = _install_two_floor_building(g)

    # Ascend first so we're on the upper floor with a valid level.
    g._on_level_entered(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))
    assert g.level.floor_index == 1

    # Now descend back.
    g._on_level_entered(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=1,
    ))

    assert g.level.floor_index == 0
    pos = g.world.get_component(g.player_id, "Position")
    assert (pos.x, pos.y) == from_tile, (
        "descending from an upper floor must place the player on "
        "the ground floor's stairs_up tile (the cross-floor link's "
        f"from_tile {from_tile}), not the room-center fallback"
    )

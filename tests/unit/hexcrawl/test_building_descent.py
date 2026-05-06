"""Game-level tests for building descent entry and exit.

A ``Building`` with a ``descent: DungeonRef`` set carries a
``stairs_down`` tile on its ground floor that routes through the
dungeon template pipeline (``procedural:crypt`` by default). When
the player uses :class:`DescendStairsAction` on that tile the
engine generates a descent Level under a dedicated cache key and
stashes the source building; ascending from the descent back to
the building ground uses the mirror path, restoring the stashed
entities and placing the player on the descent source tile.
"""

from __future__ import annotations

import pytest

from nhc.core.actions._movement import (
    AscendStairsAction, DescendStairsAction,
)
from nhc.core.events import LevelEntered
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
        template="procedural:radial",
        depth=1,
        site_kind="tower",
    )
    g.hex_player_position = coord


def _find_descent_link(building):
    from nhc.hexcrawl.model import DungeonRef as DRef
    for link in building.stair_links:
        if isinstance(link.to_floor, DRef):
            return link
    return None


def _force_tower_with_descent(g: Game) -> None:
    """Keep re-assembling towers until the first building has a
    descent; fallback fails the test."""
    import random as _random

    from nhc.sites.tower import assemble_tower
    from nhc.hexcrawl.model import DungeonRef as DRef

    for seed in range(500):
        site = assemble_tower(
            f"site_{g.hex_player_position.q}_"
            f"{g.hex_player_position.r}",
            _random.Random(seed),
        )
        if site.buildings[0].descent is not None:
            g.level = site.buildings[0].ground
            g._active_site = site
            g._floor_cache[g._cache_key(1)] = (g.level, {})
            for i, floor in enumerate(
                site.buildings[0].floors,
            ):
                g._floor_cache[g._cache_key(i + 1)] = (floor, {})
            pos = g.world.get_component(g.player_id, "Position")
            pos.level_id = g.level.id
            return
    pytest.fail("no tower with descent in 500 seeds")


@pytest.mark.asyncio
async def test_descend_from_building_ground_routes_to_descent(
    tmp_path,
) -> None:
    """Using DescendStairsAction on the descent tile swaps to a
    freshly-generated descent level, not an upper floor."""
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    _force_tower_with_descent(g)
    building = g._active_site.buildings[0]
    link = _find_descent_link(building)
    assert link is not None
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = link.from_tile
    # Emit LevelEntered directly (same as DescendStairsAction).
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id,
            level_id=g.level.id,
            depth=g.level.depth + 1,
        )
    )
    # The descent Level was swapped in (building_id is None on
    # procedural levels).
    assert g.level is not None
    assert g.level.building_id is None
    # Bookkeeping
    assert g._active_descent_building is building
    assert g._active_descent_return_tile == link.from_tile


@pytest.mark.asyncio
async def test_ascend_from_descent_returns_to_building_ground(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    _force_tower_with_descent(g)
    building = g._active_site.buildings[0]
    link = _find_descent_link(building)
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = link.from_tile
    # Enter descent
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id,
            level_id=g.level.id,
            depth=g.level.depth + 1,
        )
    )
    assert g._active_descent_building is building
    descent_level = g.level
    # Now ascend.
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id,
            level_id=descent_level.id,
            depth=1,
        )
    )
    assert g.level is building.ground
    assert g._active_descent_building is None
    assert g._active_descent_return_tile is None
    pos2 = g.world.get_component(g.player_id, "Position")
    assert (pos2.x, pos2.y) == link.from_tile


@pytest.mark.asyncio
async def test_descent_level_is_cached_for_re_entry(tmp_path) -> None:
    g = _make_game(tmp_path)
    _attach_tower_site(g, HexCoord(0, 0))
    _force_tower_with_descent(g)
    building = g._active_site.buildings[0]
    link = _find_descent_link(building)
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = link.from_tile
    # Descend once
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id,
            level_id=g.level.id,
            depth=g.level.depth + 1,
        )
    )
    first_descent = g.level
    # Ascend
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id, level_id=first_descent.id,
            depth=1,
        )
    )
    assert g.level is building.ground
    pos.x, pos.y = link.from_tile
    # Descend again -- must restore the same Level instance.
    g._on_level_entered(
        LevelEntered(
            entity=g.player_id, level_id=g.level.id,
            depth=g.level.depth + 1,
        )
    )
    assert g.level is first_descent

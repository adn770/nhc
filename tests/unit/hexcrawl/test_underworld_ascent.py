"""Ascending from an underworld floor routes to the current sector.

Cluster members share a single underworld floor. The player may
descend from hex A, walk across to hex B's sector on the shared
floor, and ascend via B's stairs_up. The surface hex they return
to must be B, not A.
"""

from __future__ import annotations

import pytest

from nhc.core.events import LevelEntered
from nhc.core.game import Game
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.mode import GameMode
from nhc.hexcrawl.model import DungeonRef, HexFeatureType
from nhc.hexcrawl.underworld import build_regions
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
        world_mode=GameMode.HEX_EASY,
        save_dir=tmp_path,
        seed=42,
    )
    g.initialize()
    return g


def _attach_cave_cluster(
    g: Game, members: list[HexCoord],
) -> None:
    """Attach a cave feature + cluster to every member hex."""
    for coord in members:
        cell = g.hex_world.cells[coord]
        cell.feature = HexFeatureType.CAVE
        cell.dungeon = DungeonRef(
            template="procedural:cave", depth=2,
            cluster_id=members[0],
        )
    g.hex_world.cave_clusters = {members[0]: list(members)}
    g.hex_world.underworld_regions = build_regions(
        g.hex_world.cave_clusters,
    )


@pytest.mark.asyncio
async def test_underworld_sector_map_populated_on_descent(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    members = [HexCoord(0, 0), HexCoord(1, 0), HexCoord(0, 1)]
    _attach_cave_cluster(g, members)
    g.hex_player_position = members[0]

    await g.enter_hex_feature()
    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))

    assert g.level.depth == 2
    assert g._underworld_sector_map, (
        "sector map should be populated after underworld generation"
    )
    for key, xy in g._cave_floor2_stairs.items():
        assert xy in g._underworld_sector_map


@pytest.mark.asyncio
async def test_ascending_from_sibling_sector_updates_hex_position(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    members = [HexCoord(0, 0), HexCoord(1, 0), HexCoord(0, 1)]
    _attach_cave_cluster(g, members)
    g.hex_player_position = members[0]

    await g.enter_hex_feature()
    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))
    assert g.level.depth == 2

    # Teleport the player onto member B's stairs_up
    key_b = f"{members[1].q}_{members[1].r}"
    bx, by = g._cave_floor2_stairs[key_b]
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = bx, by

    # Ascend from the underworld floor
    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=1,
    ))

    # hex_player_position should now match member B
    assert g.hex_player_position == members[1]


@pytest.mark.asyncio
async def test_ascending_from_original_sector_leaves_position_alone(
    tmp_path,
) -> None:
    g = _make_game(tmp_path)
    members = [HexCoord(0, 0), HexCoord(1, 0)]
    _attach_cave_cluster(g, members)
    g.hex_player_position = members[0]

    await g.enter_hex_feature()
    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=2,
    ))

    key_a = f"{members[0].q}_{members[0].r}"
    ax, ay = g._cave_floor2_stairs[key_a]
    pos = g.world.get_component(g.player_id, "Position")
    pos.x, pos.y = ax, ay

    await g.event_bus.emit(LevelEntered(
        entity=g.player_id, level_id=g.level.id, depth=1,
    ))
    assert g.hex_player_position == members[0]

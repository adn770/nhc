"""Expedition party + dungeon selection (M-2.4).

Two rules:

1. **Expedition cap.** In hex mode the overland roster may hold
   up to :data:`MAX_EXPEDITION` henchmen (larger than the dungeon
   :data:`MAX_HENCHMEN` cap). Recruit actions validate against
   the mode-appropriate cap.

2. **Dungeon selection.** A non-settlement hex (cave / ruin) can
   only fit the standard :data:`MAX_HENCHMEN` in the crawl; the
   rest of the expedition waits on the overland tile. Settlements
   (town levels) have no such cap -- the whole expedition comes
   inside. On exit the in-dungeon henchmen return to overland
   level-id alongside the player.
"""

from __future__ import annotations

import pytest

from nhc.core.actions._henchman import (
    MAX_EXPEDITION,
    MAX_HENCHMEN,
    RecruitAction,
)
from nhc.core.ecs import World
from nhc.core.game import Game
from nhc.entities.components import BlocksMovement, Henchman, Player, Position
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


def _settle_on(g: Game, feature: HexFeatureType, template: str) -> HexCoord:
    coord = g.hex_player_position
    cell = g.hex_world.cells[coord]
    cell.feature = feature
    cell.dungeon = DungeonRef(template=template)
    return coord


def _stub_hired_henchmen(g: Game, count: int) -> list[int]:
    """Create `count` already-hired henchmen attached to the player.

    They live on the overland (Position.level_id == 'overland') until
    a dungeon entry pulls some of them in.
    """
    ids: list[int] = []
    for i in range(count):
        eid = g.world.create_entity({
            "Henchman": Henchman(
                level=1, hired=True, owner=g.player_id,
            ),
            "Position": Position(x=-1, y=-1, level_id="overland"),
        })
        ids.append(eid)
    return ids


# ---------------------------------------------------------------------------
# Constants + recruit cap
# ---------------------------------------------------------------------------


def test_expedition_cap_is_larger_than_dungeon_cap() -> None:
    assert MAX_EXPEDITION > MAX_HENCHMEN


@pytest.mark.asyncio
async def test_recruit_allows_expedition_cap() -> None:
    """RecruitAction accepts a max_party override so hex-mode flows
    can hire past the classic dungeon cap."""
    world = World()
    pid = world.create_entity({
        "Position": Position(x=0, y=0, level_id="overland"),
        "Player": Player(gold=10_000),
    })
    # Fill up to MAX_HENCHMEN first.
    for _ in range(MAX_HENCHMEN):
        world.create_entity({
            "Henchman": Henchman(level=1, hired=True, owner=pid),
            "Position": Position(x=0, y=0, level_id="overland"),
        })
    # One extra unhired candidate next to the player.
    tid = world.create_entity({
        "Henchman": Henchman(level=1),
        "Position": Position(x=1, y=0, level_id="overland"),
        "BlocksMovement": BlocksMovement(),
    })
    action = RecruitAction(
        actor=pid, target=tid, max_party=MAX_EXPEDITION,
    )
    assert await action.validate(world, None)
    await action.execute(world, None)
    hench = world.get_component(tid, "Henchman")
    assert hench.hired is True, (
        "hire should succeed under expedition cap"
    )


@pytest.mark.asyncio
async def test_recruit_default_cap_still_max_henchmen() -> None:
    """Backwards-compat: omitting max_party uses MAX_HENCHMEN."""
    world = World()
    pid = world.create_entity({
        "Position": Position(x=0, y=0, level_id="overland"),
        "Player": Player(gold=10_000),
    })
    for _ in range(MAX_HENCHMEN):
        world.create_entity({
            "Henchman": Henchman(level=1, hired=True, owner=pid),
            "Position": Position(x=0, y=0, level_id="overland"),
        })
    tid = world.create_entity({
        "Henchman": Henchman(level=1),
        "Position": Position(x=1, y=0, level_id="overland"),
        "BlocksMovement": BlocksMovement(),
    })
    action = RecruitAction(actor=pid, target=tid)
    assert await action.validate(world, None)
    await action.execute(world, None)
    hench = world.get_component(tid, "Henchman")
    assert hench.hired is False, (
        "hire should fail under default dungeon cap"
    )


# ---------------------------------------------------------------------------
# Dungeon entry: left-behinds stay on overland
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enter_dungeon_brings_only_max_henchmen(tmp_path) -> None:
    """Stepping into a cave with four hired henchmen pulls only the
    first MAX_HENCHMEN into the dungeon; the remainder keep
    level_id='overland' so they wait on the overland tile."""
    g = _make_hex_game(tmp_path)
    # Give the player more than MAX_HENCHMEN.
    hench_ids = _stub_hired_henchmen(g, MAX_HENCHMEN + 2)
    _settle_on(g, HexFeatureType.CAVE, "procedural:cave")

    await g.enter_hex_feature()

    level_id = g.level.id
    in_dungeon = [
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == level_id
    ]
    left_behind = [
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == "overland"
    ]
    assert len(in_dungeon) == MAX_HENCHMEN
    assert len(left_behind) == 2


@pytest.mark.asyncio
async def test_enter_settlement_brings_entire_expedition(tmp_path) -> None:
    """Towns are social hubs: the whole expedition comes inside,
    even when it exceeds MAX_HENCHMEN. Social shops / temples /
    the inn should be reachable to the full roster."""
    g = _make_hex_game(tmp_path)
    hench_ids = _stub_hired_henchmen(g, MAX_HENCHMEN + 2)
    _settle_on(g, HexFeatureType.CITY, "procedural:settlement")

    await g.enter_hex_feature()
    level_id = g.level.id
    in_town = [
        eid for eid in hench_ids
        if g.world.get_component(eid, "Position").level_id == level_id
    ]
    assert len(in_town) == len(hench_ids), (
        f"all {len(hench_ids)} hired henchmen should enter the town, "
        f"got {len(in_town)}"
    )


@pytest.mark.asyncio
async def test_exit_dungeon_returns_henchmen_to_overland(tmp_path) -> None:
    """After the player exits, any henchman whose Position is on the
    level we're leaving resets to level_id='overland'. Left-behinds
    are already on 'overland' and are untouched."""
    g = _make_hex_game(tmp_path)
    hench_ids = _stub_hired_henchmen(g, MAX_HENCHMEN + 1)
    _settle_on(g, HexFeatureType.CAVE, "procedural:cave")

    await g.enter_hex_feature()
    await g.exit_dungeon_to_hex()

    for eid in hench_ids:
        pos = g.world.get_component(eid, "Position")
        assert pos.level_id == "overland", (
            f"henchman {eid} should be on overland after exit, "
            f"got level_id={pos.level_id}"
        )

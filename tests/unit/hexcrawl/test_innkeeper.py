"""Innkeeper NPC + rumor-listen action.

Generation side: town generator places one innkeeper at the
centre of the inn room, tagged with :class:`RumorVendor` so
:class:`BumpAction` dispatches an interact when the player
bumps into it.

Action side: :class:`InnkeeperInteractAction` pops the next
rumor off :attr:`HexWorld.active_rumors` (via
:func:`gather_rumor_at`), applies its reveal side-effect, and
emits a :class:`MessageEvent` describing the lead.
"""

from __future__ import annotations

import random

import pytest

from nhc.core.actions._innkeeper import InnkeeperInteractAction
from nhc.core.actions._movement import BumpAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.entities.components import (
    BlocksMovement,
    Health,
    Player,
    Position,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    HexCell,
    HexFeatureType,
    HexWorld,
    Rumor,
)
from nhc.hexcrawl.town import generate_town
from nhc.i18n import init as i18n_init


@pytest.fixture(scope="module", autouse=True)
def _bootstrap():
    i18n_init("en")
    EntityRegistry.discover_all()


# ---------------------------------------------------------------------------
# Generation: inn room gets an innkeeper
# ---------------------------------------------------------------------------


def _inn_room(level):
    return next(r for r in level.rooms if "inn" in r.tags)


def test_generate_town_places_innkeeper_in_inn() -> None:
    level = generate_town(seed=1)
    innkeepers = [
        p for p in level.entities
        if p.entity_id == "innkeeper"
    ]
    assert len(innkeepers) == 1
    p = innkeepers[0]
    rect = _inn_room(level).rect
    assert rect.x <= p.x < rect.x + rect.width
    assert rect.y <= p.y < rect.y + rect.height


def test_innkeeper_factory_registers_rumor_vendor() -> None:
    comps = EntityRegistry.get_creature("innkeeper")
    assert "RumorVendor" in comps


# ---------------------------------------------------------------------------
# Bump dispatch: bumping an innkeeper opens the listen action
# ---------------------------------------------------------------------------


def _make_player(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town"),
        "Player": Player(gold=0),
        "Stats": Stats(
            strength=0, dexterity=0, constitution=0,
            intelligence=0, wisdom=0, charisma=0,
        ),
        "Health": Health(current=10, maximum=10),
        "Renderable": Renderable(glyph="@", color="white",
                                  render_order=10),
    })


def _make_innkeeper(world: World, x: int, y: int) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="town"),
        "Renderable": Renderable(glyph="I", color="yellow",
                                  render_order=2),
        "BlocksMovement": BlocksMovement(),
        "RumorVendor": RumorVendor(),
    })


def _flat_level(width: int = 10, height: int = 10):
    """Create a small floor-only level so BumpAction.resolve can
    complete its door-blocking check (which hits ``level.tile_at``)."""
    from nhc.dungeon.model import Level, Terrain, Tile
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    return Level(
        id="town", name="town", depth=1,
        width=width, height=height, tiles=tiles,
    )


def test_bumping_innkeeper_returns_interact_action() -> None:
    world = World()
    pid = _make_player(world, x=5, y=5)
    _make_innkeeper(world, x=6, y=5)
    bump = BumpAction(actor=pid, dx=1, dy=0)
    resolved = bump.resolve(world, level=_flat_level())
    assert isinstance(resolved, InnkeeperInteractAction)


# ---------------------------------------------------------------------------
# Action execute: draws a rumor and reveals its target
# ---------------------------------------------------------------------------


def _mini_hex_world() -> HexWorld:
    w = HexWorld(pack_id="test", seed=0, width=4, height=4)
    for q in range(3):
        for r in range(3):
            c = HexCoord(q=q, r=r)
            w.cells[c] = HexCell(
                coord=c,
                feature=HexFeatureType.NONE,
                biome=__import__(
                    "nhc.hexcrawl.model", fromlist=["Biome"],
                ).Biome.GREENLANDS,
            )
    return w


@pytest.mark.asyncio
async def test_innkeeper_interact_consumes_rumor(tmp_path) -> None:
    # Build a minimal game-like shape so the action can reach the
    # HexWorld via the world components + a caller-supplied hook.
    world = World()
    pid = _make_player(world, x=0, y=0)
    inn_id = _make_innkeeper(world, x=1, y=0)

    hex_world = _mini_hex_world()
    target = HexCoord(q=2, r=2)
    hex_world.active_rumors = [
        Rumor(id="r1", text_key="rumor.true_feature",
              truth=True, reveals=target),
    ]

    action = InnkeeperInteractAction(
        actor=pid, innkeeper_id=inn_id, hex_world=hex_world,
    )
    assert await action.validate(world, None) is True
    events = await action.execute(world, None)

    # The rumor is gone, the coord is revealed, and the action
    # emitted a message so the player sees the lead.
    assert hex_world.active_rumors == []
    assert target in hex_world.revealed
    assert any(isinstance(e, MessageEvent) for e in events)


@pytest.mark.asyncio
async def test_innkeeper_interact_empty_pool_emits_no_rumor_msg(
    tmp_path,
) -> None:
    world = World()
    pid = _make_player(world, x=0, y=0)
    inn_id = _make_innkeeper(world, x=1, y=0)
    hex_world = _mini_hex_world()
    hex_world.active_rumors = []

    action = InnkeeperInteractAction(
        actor=pid, innkeeper_id=inn_id, hex_world=hex_world,
    )
    events = await action.execute(world, None)
    # Should still emit a message so the player gets feedback.
    msgs = [e for e in events if isinstance(e, MessageEvent)]
    assert msgs, "action should say something even on empty pool"

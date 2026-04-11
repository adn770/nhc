"""Tests for the player's retreat-narration cue.

When the player takes a step that strictly increases the minimum
Chebyshev distance to any visible hostile creature, MoveAction
appends an ``explore.retreat`` MessageEvent. This gives tactile
feedback when disengaging from morale-broken or hesitant
creatures.
"""

import pytest

from nhc.core.actions import MoveAction
from nhc.core.ecs import World
from nhc.core.events import MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI,
    BlocksMovement,
    Description,
    Health,
    Player,
    Position,
    Renderable,
    Stats,
)
from nhc.i18n import init as i18n_init


pytestmark = pytest.mark.core


def _make_level(w: int = 12, h: int = 12) -> Level:
    tiles = [[Tile(terrain=Terrain.FLOOR, visible=True)
              for _ in range(w)] for _ in range(h)]
    for x in range(w):
        tiles[0][x].terrain = Terrain.WALL
        tiles[h - 1][x].terrain = Terrain.WALL
    for y in range(h):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][w - 1].terrain = Terrain.WALL
    return Level(
        id="t", name="T", depth=1, width=w, height=h,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )


def _make_player(world: World, x: int = 5, y: int = 5) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=20, maximum=20),
        "Player": Player(),
        "Description": Description(name="Hero"),
        "Renderable": Renderable(glyph="@"),
    })


def _make_hostile(
    world: World, x: int, y: int, behavior: str = "aggressive_melee",
) -> int:
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=1, dexterity=1),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior=behavior, morale=7, faction="goblinoid"),
        # No BlocksMovement so we can build adjacent positions
        # cleanly without worrying about MoveAction.validate.
        "Description": Description(name="Goblin", gender="m"),
        "Renderable": Renderable(glyph="g"),
    })


@pytest.fixture(autouse=True)
def _i18n():
    i18n_init("en")


def _retreat_text() -> str:
    from nhc.i18n import t
    return t("explore.retreat")


class TestPlayerRetreatNarration:
    @pytest.mark.asyncio
    async def test_step_away_from_visible_hostile_emits_retreat(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        _make_hostile(world, 6, 5)  # adjacent east

        # Step west: distance to goblin grows from 1 to 2.
        action = MoveAction(actor=pid, dx=-1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert len(retreat_msgs) == 1

    @pytest.mark.asyncio
    async def test_step_parallel_no_retreat_message(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        _make_hostile(world, 6, 5)

        # Step north: distance stays at 1 (chebyshev).
        action = MoveAction(actor=pid, dx=0, dy=-1)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert retreat_msgs == []

    @pytest.mark.asyncio
    async def test_no_hostiles_no_retreat_message(self):
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        # No creatures at all.

        action = MoveAction(actor=pid, dx=-1, dy=0)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert retreat_msgs == []

    @pytest.mark.asyncio
    async def test_invisible_hostile_does_not_count(self):
        """A goblin sitting on an unseen tile should not trigger
        retreat narration — the player has not noticed it."""
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        _make_hostile(world, 6, 5)
        # Hide the goblin's tile from FOV.
        level.tiles[5][6].visible = False

        action = MoveAction(actor=pid, dx=-1, dy=0)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert retreat_msgs == []

    @pytest.mark.asyncio
    async def test_idle_creature_does_not_count_as_hostile(self):
        """A merchant (idle behaviour) is not a threat — moving
        away from one should not narrate a retreat."""
        world = World()
        level = _make_level()
        pid = _make_player(world, x=5, y=5)
        _make_hostile(world, 6, 5, behavior="idle")

        action = MoveAction(actor=pid, dx=-1, dy=0)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert retreat_msgs == []

    @pytest.mark.asyncio
    async def test_non_player_actor_does_not_emit_retreat(self):
        """Only the player gets retreat narration — non-player
        moves stay quiet."""
        world = World()
        level = _make_level()
        _make_player(world, x=5, y=5)
        # Make a hostile move; it should never produce a retreat
        # message regardless of geometry.
        gid = _make_hostile(world, 7, 5)

        action = MoveAction(actor=gid, dx=1, dy=0)
        events = await action.execute(world, level)

        retreat_msgs = [
            e for e in events
            if isinstance(e, MessageEvent) and "back" in e.text.lower()
        ]
        assert retreat_msgs == []

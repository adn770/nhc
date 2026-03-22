"""Tests for CustomAction and ImpossibleAction."""

import pytest

from nhc.core.actions import CustomAction, ImpossibleAction
from nhc.core.ecs import World
from nhc.core.events import CustomActionEvent, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import Position, Stats


def _make_world_and_level():
    """Create a minimal world with a player for testing."""
    world = World()
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(5)]
             for _ in range(5)]
    level = Level(
        id="test", name="Test", depth=1, width=5, height=5,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )

    player_id = world.create_entity({
        "Position": Position(x=2, y=2),
        "Stats": Stats(strength=2, dexterity=3, constitution=1,
                       intelligence=1, wisdom=2, charisma=0),
    })
    return world, level, player_id


class TestCustomAction:
    @pytest.mark.asyncio
    async def test_executes_ability_check(self):
        world, level, pid = _make_world_and_level()
        action = CustomAction(pid, description="listen at door",
                              ability="wisdom", dc=10)
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        assert len(events) == 1
        ev = events[0]
        assert isinstance(ev, CustomActionEvent)
        assert ev.ability == "wisdom"
        assert ev.bonus == 2  # wisdom stat value
        assert ev.dc == 10
        assert 1 <= ev.roll <= 20

    @pytest.mark.asyncio
    async def test_success_when_high_roll(self):
        """With bonus 2 and DC 3, almost always succeeds."""
        world, level, pid = _make_world_and_level()
        successes = 0
        for _ in range(100):
            action = CustomAction(pid, description="easy task",
                                  ability="dexterity", dc=3)
            events = await action.execute(world, level)
            if events[0].success:
                successes += 1
        # With d20 + 3 vs DC 3, should succeed ~100% of the time
        assert successes > 90


class TestImpossibleAction:
    @pytest.mark.asyncio
    async def test_emits_message(self):
        world, level, pid = _make_world_and_level()
        action = ImpossibleAction(pid, reason="You can't fly.")
        assert await action.validate(world, level)
        events = await action.execute(world, level)
        assert len(events) == 1
        assert isinstance(events[0], MessageEvent)
        assert "fly" in events[0].text.lower()

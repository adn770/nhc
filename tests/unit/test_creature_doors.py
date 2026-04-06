"""Tests for creature door interaction: humanoids open doors, others don't."""

import pytest

from nhc.ai.behavior import HUMANOID_FACTIONS, decide_action
from nhc.core.actions import MoveAction
from nhc.core.ecs import World
from nhc.core.events import DoorOpened, MessageEvent
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, BlocksMovement, Description, Health, Player,
    Position, Renderable, Stats,
)
from nhc.i18n import init as i18n_init
from nhc.utils.rng import set_seed


def _make_level_with_door():
    """10x10 level with a closed door at (6, 5)."""
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    tiles[5][6] = Tile(terrain=Terrain.FLOOR, feature="door_closed",
                       door_side="east")
    return Level(id="t", name="T", depth=1, width=10, height=10,
                 tiles=tiles, rooms=[], corridors=[], entities=[])


def _make_world():
    i18n_init("en")
    set_seed(42)
    return World()


def _make_creature(world, x, y, faction="beast", behavior="aggressive_melee"):
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Stats": Stats(strength=2, dexterity=1),
        "Health": Health(current=10, maximum=10),
        "AI": AI(behavior=behavior, morale=7, faction=faction),
        "BlocksMovement": BlocksMovement(),
        "Renderable": Renderable(glyph="g", color="green"),
        "Description": Description(name="Creature"),
    })


def _make_player(world, x=0, y=0):
    return world.create_entity({
        "Position": Position(x=x, y=y, level_id="t"),
        "Player": Player(),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=20, maximum=20),
        "Renderable": Renderable(glyph="@", color="white"),
        "Description": Description(name="Hero"),
    })


class TestHumanoidFactions:
    def test_goblinoid_is_humanoid(self):
        assert "goblinoid" in HUMANOID_FACTIONS

    def test_human_is_humanoid(self):
        assert "human" in HUMANOID_FACTIONS

    def test_humanoid_is_humanoid(self):
        assert "humanoid" in HUMANOID_FACTIONS

    def test_giant_is_humanoid(self):
        assert "giant" in HUMANOID_FACTIONS

    def test_gnoll_is_humanoid(self):
        assert "gnoll" in HUMANOID_FACTIONS

    def test_undead_is_humanoid(self):
        assert "undead" in HUMANOID_FACTIONS

    def test_beast_is_not_humanoid(self):
        assert "beast" not in HUMANOID_FACTIONS

    def test_ooze_is_not_humanoid(self):
        assert "ooze" not in HUMANOID_FACTIONS

    def test_plant_is_not_humanoid(self):
        assert "plant" not in HUMANOID_FACTIONS

    def test_vermin_is_not_humanoid(self):
        assert "vermin" not in HUMANOID_FACTIONS


class TestHumanoidOpensDoor:
    @pytest.mark.asyncio
    async def test_humanoid_creature_opens_closed_door(self):
        """A goblinoid creature bumping a closed door should open it."""
        world = _make_world()
        level = _make_level_with_door()
        # Creature at (5, 5), door at (6, 5), moving east (dx=1)
        cid = _make_creature(world, 5, 5, faction="goblinoid")

        action = MoveAction(actor=cid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.feature == "door_open"
        door_events = [e for e in events if isinstance(e, DoorOpened)]
        assert len(door_events) == 1

    @pytest.mark.asyncio
    async def test_human_creature_opens_door(self):
        world = _make_world()
        level = _make_level_with_door()
        cid = _make_creature(world, 5, 5, faction="human")

        action = MoveAction(actor=cid, dx=1, dy=0)
        events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.feature == "door_open"


class TestNonHumanoidBlockedByDoor:
    @pytest.mark.asyncio
    async def test_beast_cannot_open_closed_door(self):
        """A beast creature bumping a closed door should be blocked."""
        world = _make_world()
        level = _make_level_with_door()
        cid = _make_creature(world, 5, 5, faction="beast")

        action = MoveAction(actor=cid, dx=1, dy=0)
        events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.feature == "door_closed"
        # Creature didn't move
        pos = world.get_component(cid, "Position")
        assert pos.x == 5 and pos.y == 5

    @pytest.mark.asyncio
    async def test_ooze_cannot_open_closed_door(self):
        world = _make_world()
        level = _make_level_with_door()
        cid = _make_creature(world, 5, 5, faction="ooze")

        action = MoveAction(actor=cid, dx=1, dy=0)
        events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.feature == "door_closed"

    @pytest.mark.asyncio
    async def test_plant_cannot_open_closed_door(self):
        world = _make_world()
        level = _make_level_with_door()
        cid = _make_creature(world, 5, 5, faction="plant")

        action = MoveAction(actor=cid, dx=1, dy=0)
        events = await action.execute(world, level)

        tile = level.tile_at(6, 5)
        assert tile.feature == "door_closed"

    @pytest.mark.asyncio
    async def test_beast_can_walk_through_open_door(self):
        """Non-humanoid can move through an already-open door."""
        world = _make_world()
        level = _make_level_with_door()
        level.tile_at(6, 5).feature = "door_open"
        cid = _make_creature(world, 5, 5, faction="beast")

        action = MoveAction(actor=cid, dx=1, dy=0)
        assert await action.validate(world, level)
        events = await action.execute(world, level)

        pos = world.get_component(cid, "Position")
        assert pos.x == 6 and pos.y == 5


class TestNonHumanoidPathfinding:
    def test_beast_pathfinding_avoids_closed_door(self):
        """Non-humanoid AI should not pathfind through closed doors."""
        world = _make_world()
        level = _make_level_with_door()
        # Creature at (5, 5), player at (7, 5) — door at (6, 5)
        cid = _make_creature(world, 5, 5, faction="beast")
        pid = _make_player(world, 7, 5)

        action = decide_action(cid, world, level, pid)
        # If path is blocked by door, creature should try to go around
        # or return None if no path exists
        if action is not None:
            assert isinstance(action, MoveAction)
            # Should NOT be moving east into the door
            assert not (action.dx == 1 and action.dy == 0)

    def test_humanoid_pathfinding_goes_through_door(self):
        """Humanoid AI should pathfind through closed doors."""
        world = _make_world()
        level = _make_level_with_door()
        # Creature at (5, 5), player at (7, 5) — door at (6, 5)
        cid = _make_creature(world, 5, 5, faction="goblinoid")
        pid = _make_player(world, 7, 5)

        action = decide_action(cid, world, level, pid)
        assert isinstance(action, MoveAction)
        # Should move toward the player (dx > 0)
        assert action.dx == 1

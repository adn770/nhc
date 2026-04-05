"""Tests for directional door crossing behavior."""

import asyncio

import pytest

from nhc.core.actions import MoveAction, _crossing_door_edge
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Room, Rect, Terrain, Tile
from nhc.entities.components import Health, Player, Position, Renderable, Stats


def _make_corridor_door_room():
    """Create: corridor(4,3) → door(3,3, side=west) → room(2,3).

    The door is on the west edge of tile (3,3), connecting to room
    tiles at (1,3) and (2,3). Corridor at (4,3).

    Layout (y=3 row): [room][room][door|west][corridor]
                        x=1   x=2    x=3       x=4
    """
    level = Level.create_empty("t", "T", depth=1, width=6, height=6)
    # Room floor
    for x in range(1, 3):
        level.tiles[3][x] = Tile(terrain=Terrain.FLOOR)
    # Door tile
    level.tiles[3][3] = Tile(
        terrain=Terrain.FLOOR, feature="door_closed", door_side="west",
    )
    # Corridor
    level.tiles[3][4] = Tile(terrain=Terrain.FLOOR, is_corridor=True)
    level.rooms.append(Room(id="r", rect=Rect(1, 2, 2, 3)))
    return level


def _make_player(world, x, y):
    pid = world.create_entity()
    world.add_component(pid, "Position", Position(x=x, y=y))
    world.add_component(pid, "Player", Player())
    world.add_component(pid, "Stats", Stats())
    world.add_component(pid, "Health", Health(current=10, maximum=10))
    world.add_component(pid, "Renderable", Renderable(glyph="@"))
    return pid


class TestCrossingDoorEdge:
    def test_east_door_entering_from_east(self):
        tile = Tile(feature="door_closed", door_side="east")
        # Entering from east means moving west (dx=-1)
        assert _crossing_door_edge(-1, 0, tile, entering=True) is True

    def test_east_door_entering_from_west(self):
        tile = Tile(feature="door_closed", door_side="east")
        # Entering from west means moving east (dx=+1) — not crossing
        assert _crossing_door_edge(1, 0, tile, entering=True) is False

    def test_east_door_leaving_toward_east(self):
        tile = Tile(feature="door_closed", door_side="east")
        assert _crossing_door_edge(1, 0, tile, entering=False) is True

    def test_east_door_leaving_toward_west(self):
        tile = Tile(feature="door_closed", door_side="east")
        assert _crossing_door_edge(-1, 0, tile, entering=False) is False

    def test_west_door_entering_from_west(self):
        tile = Tile(feature="door_closed", door_side="west")
        # Entering from west means moving east (dx=+1)
        assert _crossing_door_edge(1, 0, tile, entering=True) is True

    def test_west_door_entering_from_east(self):
        tile = Tile(feature="door_closed", door_side="west")
        # Entering from east means moving west — not crossing
        assert _crossing_door_edge(-1, 0, tile, entering=True) is False

    def test_north_door_entering_from_north(self):
        tile = Tile(feature="door_closed", door_side="north")
        assert _crossing_door_edge(0, 1, tile, entering=True) is True

    def test_vertical_move_doesnt_cross_east_door(self):
        tile = Tile(feature="door_closed", door_side="east")
        assert _crossing_door_edge(0, 1, tile, entering=True) is False

    def test_no_side_always_crosses(self):
        tile = Tile(feature="door_closed", door_side="")
        assert _crossing_door_edge(1, 0, tile, entering=True) is True


class TestDoorMovement:
    """Test that players can walk onto door tiles from corridor side."""

    async def test_walk_onto_door_from_corridor_side(self):
        """Edge mode: moving from corridor onto door (non-door edge) = move."""
        level = _make_corridor_door_room()
        world = World()
        pid = _make_player(world, 4, 3)

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=True)
        assert await action.validate(world, level)
        await action.execute(world, level)
        pos = world.get_component(pid, "Position")
        assert pos.x == 3
        assert pos.y == 3
        assert level.tiles[3][3].feature == "door_closed"

    async def test_crossing_door_from_door_tile(self):
        """Edge mode: leaving door tile toward room = opens."""
        level = _make_corridor_door_room()
        world = World()
        pid = _make_player(world, 3, 3)

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=True)
        await action.execute(world, level)
        assert level.tiles[3][3].feature == "door_open"
        pos = world.get_component(pid, "Position")
        assert pos.x == 3  # didn't move, door open consumed action

    async def test_walk_onto_door_from_room_side_triggers(self):
        """Edge mode: entering door tile from room side = opens."""
        level = _make_corridor_door_room()
        world = World()
        pid = _make_player(world, 2, 3)

        action = MoveAction(actor=pid, dx=1, dy=0, edge_doors=True)
        await action.execute(world, level)
        assert level.tiles[3][3].feature == "door_open"

    async def test_walk_onto_secret_door_from_corridor(self):
        """Edge mode: can walk onto secret door tile from corridor side."""
        level = _make_corridor_door_room()
        level.tiles[3][3].feature = "door_secret"
        world = World()
        pid = _make_player(world, 4, 3)

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=True)
        assert await action.validate(world, level)
        await action.execute(world, level)
        pos = world.get_component(pid, "Position")
        assert pos.x == 3  # moved onto the tile
        assert level.tiles[3][3].feature == "door_secret"  # still secret

    async def test_secret_door_blocks_crossing(self):
        """Edge mode: can't cross through secret door edge."""
        level = _make_corridor_door_room()
        level.tiles[3][3].feature = "door_secret"
        world = World()
        pid = _make_player(world, 3, 3)  # on the secret door tile

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=True)
        await action.execute(world, level)
        # Blocked — feels like a wall
        pos = world.get_component(pid, "Position")
        assert pos.x == 3  # didn't move
        assert level.tiles[3][3].feature == "door_secret"  # still secret

    async def test_secret_door_terminal_mode_blocks(self):
        """Center mode: secret doors are not walkable at all."""
        level = _make_corridor_door_room()
        level.tiles[3][3].feature = "door_secret"
        world = World()
        pid = _make_player(world, 4, 3)

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=False)
        valid = await action.validate(world, level)
        assert not valid  # can't walk onto secret door in terminal

    async def test_terminal_mode_bump_opens_immediately(self):
        """Center mode (terminal): bumping door tile opens it."""
        level = _make_corridor_door_room()
        world = World()
        pid = _make_player(world, 4, 3)

        action = MoveAction(actor=pid, dx=-1, dy=0, edge_doors=False)
        await action.execute(world, level)
        # Terminal: bump opens immediately
        assert level.tiles[3][3].feature == "door_open"
        # Player stays at corridor (door open consumed action)
        pos = world.get_component(pid, "Position")
        assert pos.x == 4


class TestBumpThroughClosedDoorWithCreatureBehind:
    """Regression: a creature standing on the far side of a
    closed edge-door used to hijack BumpAction into a melee
    that could never land (blocked by _closed_door_blocks),
    leaving the door closed and stalling the player. The bump
    must fall through to MoveAction so the door gets opened
    first."""

    def _make_level_with_creature_behind_door(self):
        """Player on door tile (3,3, door_side=west), room
        floors at (1,3) and (2,3), corridor (4,3). A creature
        with BlocksMovement sits at (2,3) behind the door."""
        from nhc.core.actions import BumpAction
        from nhc.entities.components import BlocksMovement
        level = _make_corridor_door_room()
        world = World()
        pid = _make_player(world, 3, 3)  # on the door tile
        # Creature on the room side of the door.
        cid = world.create_entity()
        world.add_component(cid, "Position", Position(x=2, y=3))
        world.add_component(cid, "BlocksMovement", BlocksMovement())
        world.add_component(cid, "Renderable", Renderable(glyph="g"))
        return level, world, pid, cid

    async def test_bump_opens_door_when_creature_behind(self):
        from nhc.core.actions import BumpAction
        level, world, pid, cid = (
            self._make_level_with_creature_behind_door())
        bump = BumpAction(actor=pid, dx=-1, dy=0, edge_doors=True)
        assert await bump.validate(world, level)
        events = await bump.execute(world, level)
        # Door must be open now, not a silent no-op.
        assert level.tiles[3][3].feature == "door_open", (
            "bump toward a creature behind a closed door should "
            "open the door instead of stalling on a blocked "
            "melee attack"
        )
        # Player stays on the door tile — opening consumed the turn.
        pos = world.get_component(pid, "Position")
        assert (pos.x, pos.y) == (3, 3)
        # Events should include a DoorOpened-style response.
        assert events, "bump must emit events (door-open)"

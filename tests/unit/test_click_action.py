"""Tests for click-to-action resolution."""

import pytest

from nhc.core.actions import BumpAction, PickupItemAction, WaitAction
from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import (
    AI, Description, Health, Inventory, Player, Position, Renderable, Stats,
)


def _make_world_and_level():
    """Create a small world with a player at (5,5) on a floor grid."""
    world = World()
    level = Level.create_empty("test", "Test", depth=1, width=12, height=12)
    # Carve floor around (5,5)
    for y in range(3, 9):
        for x in range(3, 9):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    # Player at (5,5)
    pid = world.create_entity()
    world.add_component(pid, "Position", Position(x=5, y=5))
    world.add_component(pid, "Player", Player())
    world.add_component(pid, "Stats", Stats())
    world.add_component(pid, "Health", Health(current=10, maximum=10))
    world.add_component(pid, "Inventory", Inventory())
    world.add_component(pid, "Renderable", Renderable(glyph="@"))

    return world, level, pid


class TestResolveClick:
    def test_click_adjacent_produces_move(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        # Click one tile north of player
        action = _resolve_click(world, level, pid, 5, 4)
        assert isinstance(action, BumpAction)
        assert action.dx == 0
        assert action.dy == -1

    def test_click_diagonal_produces_move(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        action = _resolve_click(world, level, pid, 6, 4)
        assert isinstance(action, BumpAction)
        assert action.dx == 1
        assert action.dy == -1

    def test_click_on_self_produces_wait(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        action = _resolve_click(world, level, pid, 5, 5)
        assert isinstance(action, WaitAction)

    def test_click_on_creature_produces_bump(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        # Place a goblin adjacent at (6,5)
        gob = world.create_entity()
        world.add_component(gob, "Position", Position(x=6, y=5))
        world.add_component(gob, "AI", AI())
        world.add_component(gob, "Health", Health(current=4, maximum=4))
        action = _resolve_click(world, level, pid, 6, 5)
        assert isinstance(action, BumpAction)
        assert action.dx == 1
        assert action.dy == 0

    def test_click_distant_floor_produces_move_toward(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        # Click far east — should produce a single step east
        action = _resolve_click(world, level, pid, 8, 5)
        assert isinstance(action, BumpAction)
        assert action.dx == 1
        assert action.dy == 0

    def test_click_on_wall_returns_none(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        # (1,1) is a wall/void tile
        action = _resolve_click(world, level, pid, 1, 1)
        assert action is None

    def test_click_out_of_bounds_returns_none(self):
        from nhc.core.game import _resolve_click
        world, level, pid = _make_world_and_level()
        action = _resolve_click(world, level, pid, -1, -1)
        assert action is None

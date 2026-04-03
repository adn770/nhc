"""Tests for automatic door closing after 20 turns."""

import pytest

from nhc.core.ecs import World
from nhc.core.game_ticks import DOOR_CLOSE_TURNS, tick_doors
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import Position
from nhc.i18n import init


class FakeRenderer:
    def __init__(self):
        self.messages: list[str] = []

    def add_message(self, text: str) -> None:
        self.messages.append(text)


class FakeGame:
    def __init__(self, level, world, turn=0):
        self.level = level
        self.world = world
        self.turn = turn
        self.renderer = FakeRenderer()


def _make_level(width=10, height=10):
    tiles = [
        [Tile(terrain=Terrain.FLOOR) for _ in range(width)]
        for _ in range(height)
    ]
    for x in range(width):
        tiles[0][x].terrain = Terrain.WALL
        tiles[height - 1][x].terrain = Terrain.WALL
    for y in range(height):
        tiles[y][0].terrain = Terrain.WALL
        tiles[y][width - 1].terrain = Terrain.WALL
    return Level(
        id="test", name="Test", depth=1,
        width=width, height=height, tiles=tiles,
    )


@pytest.fixture(autouse=True)
def _init_i18n():
    init("en")


def test_door_closes_after_20_turns():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    world = World()
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    tick_doors(game)

    assert tile.feature == "door_closed"
    assert tile.opened_at_turn is None


def test_door_stays_open_before_20_turns():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    world = World()
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS - 1)

    tick_doors(game)

    assert tile.feature == "door_open"


def test_door_does_not_close_with_entity_on_it():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    world = World()
    eid = world.create_entity()
    world.add_component(eid, "Position", Position(x=5, y=5))
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    tick_doors(game)

    assert tile.feature == "door_open"


def test_door_closes_after_entity_moves_away():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    world = World()
    eid = world.create_entity()
    pos = Position(x=5, y=5)
    world.add_component(eid, "Position", pos)
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    # Entity still on door
    tick_doors(game)
    assert tile.feature == "door_open"

    # Entity moves away
    pos.x = 6
    tick_doors(game)
    assert tile.feature == "door_closed"


def test_forced_locked_door_becomes_closed():
    """A door that was locked and forced open becomes door_closed,
    not door_locked, when it auto-closes."""
    level = _make_level()
    tile = level.tile_at(5, 5)
    # Simulate: was door_locked, forced open
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    world = World()
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    tick_doors(game)

    assert tile.feature == "door_closed"


def test_message_shown_when_door_visible():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    tile.visible = True
    world = World()
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    tick_doors(game)

    assert len(game.renderer.messages) == 1


def test_no_message_when_door_not_visible():
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = 0
    tile.visible = False
    world = World()
    game = FakeGame(level, world, turn=DOOR_CLOSE_TURNS)

    tick_doors(game)

    assert len(game.renderer.messages) == 0


def test_door_without_opened_at_turn_not_closed():
    """Doors opened before this feature (opened_at_turn=None)
    should not auto-close."""
    level = _make_level()
    tile = level.tile_at(5, 5)
    tile.feature = "door_open"
    tile.opened_at_turn = None
    world = World()
    game = FakeGame(level, world, turn=100)

    tick_doors(game)

    assert tile.feature == "door_open"

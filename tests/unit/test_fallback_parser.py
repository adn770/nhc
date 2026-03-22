"""Tests for the keyword-based fallback intent parser."""

from nhc.core.ecs import World
from nhc.dungeon.model import Level, Terrain, Tile
from nhc.entities.components import AI, Description, Health, Position, Stats
from nhc.narrative.fallback_parser import parse_intent_keywords


def _make_world():
    """Create a minimal world with a player and a creature."""
    world = World()
    tiles = [[Tile(terrain=Terrain.FLOOR) for _ in range(10)]
             for _ in range(10)]
    # Make all tiles visible and explored
    for row in tiles:
        for tile in row:
            tile.visible = True
            tile.explored = True
    level = Level(
        id="test", name="Test", depth=1, width=10, height=10,
        tiles=tiles, rooms=[], corridors=[], entities=[],
    )

    player_id = world.create_entity({
        "Position": Position(x=5, y=5),
        "Stats": Stats(strength=2),
        "Description": Description(name="Player"),
    })
    # Add a goblin nearby
    world.create_entity({
        "Position": Position(x=6, y=5),
        "AI": AI(behavior="aggressive_melee"),
        "Description": Description(name="Goblin"),
        "Health": Health(current=4, maximum=4),
    })
    # Add an item at player position
    world.create_entity({
        "Position": Position(x=5, y=5),
        "Description": Description(name="Healing Potion"),
    })

    return world, level, player_id


class TestFallbackParser:
    def test_move_north(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("go north", w, l, pid)
        assert plan[0]["action"] == "move"
        assert plan[0]["direction"] == "north"

    def test_move_catalan(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("anar al nord", w, l, pid)
        assert plan[0]["action"] == "move"
        assert plan[0]["direction"] == "north"

    def test_move_spanish(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("ir al sur", w, l, pid)
        assert plan[0]["action"] == "move"
        assert plan[0]["direction"] == "south"

    def test_attack(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("attack the goblin", w, l, pid)
        assert plan[0]["action"] == "attack"
        assert plan[0]["target"] is not None

    def test_pickup(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("pick up the potion", w, l, pid)
        assert plan[0]["action"] == "pickup"

    def test_look(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("look around", w, l, pid)
        assert plan[0]["action"] == "look"

    def test_wait(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("wait", w, l, pid)
        assert plan[0]["action"] == "wait"

    def test_descend(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("go down the stairs", w, l, pid)
        assert plan[0]["action"] == "descend"

    def test_empty_input(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("", w, l, pid)
        assert plan[0]["action"] == "wait"

    def test_unknown_defaults_wait(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("juggle flaming torches", w, l, pid)
        assert plan[0]["action"] == "wait"

    def test_direction_keyword_alone(self):
        w, l, pid = _make_world()
        plan = parse_intent_keywords("east", w, l, pid)
        assert plan[0]["action"] == "move"
        assert plan[0]["direction"] == "east"

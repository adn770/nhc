"""Tests for ECS system."""

from nhc.core.ecs import World
from nhc.entities.components import Health, Position, Stats


class TestWorld:
    def test_create_entity(self):
        world = World()
        eid = world.create_entity()
        assert eid == 0
        assert world.entity_count == 1

    def test_create_entity_with_components(self):
        world = World()
        eid = world.create_entity({
            "Position": Position(x=5, y=3),
            "Health": Health(current=10, maximum=10),
        })
        pos = world.get_component(eid, "Position")
        assert pos.x == 5
        assert pos.y == 3

    def test_destroy_entity(self):
        world = World()
        eid = world.create_entity({"Health": Health(current=5, maximum=5)})
        world.destroy_entity(eid)
        assert world.entity_count == 0
        assert world.get_component(eid, "Health") is None

    def test_query_single_component(self):
        world = World()
        world.create_entity({"Position": Position(x=1, y=2)})
        world.create_entity({"Position": Position(x=3, y=4)})
        world.create_entity({"Health": Health()})

        results = world.query("Position")
        assert len(results) == 2

    def test_query_multiple_components(self):
        world = World()
        world.create_entity({
            "Position": Position(x=1, y=2),
            "Stats": Stats(strength=3),
        })
        world.create_entity({"Position": Position(x=3, y=4)})

        results = world.query("Position", "Stats")
        assert len(results) == 1
        eid, pos, stats = results[0]
        assert pos.x == 1
        assert stats.strength == 3

    def test_has_component(self):
        world = World()
        eid = world.create_entity({"Health": Health()})
        assert world.has_component(eid, "Health")
        assert not world.has_component(eid, "Stats")

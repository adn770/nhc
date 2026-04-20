"""Tests for building interior partitioners.

See ``design/building_interiors.md``. Partitioners return a
``LayoutPlan`` describing rooms, interior walls, corridor tiles,
and interior doors; the site assembler stamps the plan onto the
``Level``. Partitioners never touch ``Level`` directly — this
keeps them trivially testable with pure fixtures.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import (
    CircleShape, OctagonShape, Rect, RectShape,
)


def _cfg(
    rect: Rect,
    shape=None,
    required_walkable=frozenset(),
    floor_index: int = 0,
    n_floors: int = 1,
    archetype: str = "tower",
    seed: int = 0,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=shape or RectShape(),
        floor_index=floor_index,
        n_floors=n_floors,
        rng=random.Random(seed),
        archetype=archetype,
        required_walkable=required_walkable,
    )


class TestSingleRoomPartitioner:
    def test_returns_one_room_matching_footprint(self):
        rect = Rect(1, 1, 7, 5)
        plan = SingleRoomPartitioner().plan(_cfg(rect))
        assert len(plan.rooms) == 1
        room = plan.rooms[0]
        assert room.rect.x == rect.x
        assert room.rect.y == rect.y
        assert room.rect.width == rect.width
        assert room.rect.height == rect.height

    def test_empty_walls_corridors_doors(self):
        plan = SingleRoomPartitioner().plan(_cfg(Rect(2, 2, 5, 5)))
        assert plan.interior_walls == set()
        assert plan.corridor_tiles == set()
        assert plan.doors == []

    def test_room_inherits_config_shape(self):
        shape = CircleShape()
        plan = SingleRoomPartitioner().plan(
            _cfg(Rect(1, 1, 7, 7), shape=shape),
        )
        assert plan.rooms[0].shape is shape

    def test_required_walkable_lands_on_floor(self):
        rect = Rect(1, 1, 5, 5)
        footprint = RectShape().floor_tiles(rect)
        # Pick a tile in the interior.
        required = frozenset({(3, 3)})
        assert required <= footprint

        plan = SingleRoomPartitioner().plan(
            _cfg(rect, required_walkable=required),
        )
        # Required tile must be inside the one room's floor set.
        room_tiles = plan.rooms[0].shape.floor_tiles(plan.rooms[0].rect)
        assert required <= room_tiles
        # Not a wall, not a door.
        assert plan.interior_walls.isdisjoint(required)

    def test_required_walkable_outside_shape_raises(self):
        """Caller passed a tile the shape doesn't consider walkable.
        That's a caller bug — assert, don't silently relocate."""
        shape = CircleShape()
        rect = Rect(1, 1, 7, 7)
        # A rect-corner that falls outside the circle.
        bad_tile = (rect.x, rect.y)
        assert bad_tile not in shape.floor_tiles(rect)
        with pytest.raises(AssertionError):
            SingleRoomPartitioner().plan(
                _cfg(
                    rect, shape=shape,
                    required_walkable=frozenset({bad_tile}),
                ),
            )

    def test_octagon_shape_preserved_on_room(self):
        shape = OctagonShape()
        plan = SingleRoomPartitioner().plan(
            _cfg(Rect(1, 1, 9, 9), shape=shape),
        )
        assert plan.rooms[0].shape is shape


class TestLayoutPlanDefaults:
    def test_defaults_are_empty(self):
        room = SingleRoomPartitioner().plan(
            _cfg(Rect(1, 1, 5, 5)),
        ).rooms[0]
        plan = LayoutPlan(rooms=[room])
        assert plan.interior_walls == set()
        assert plan.corridor_tiles == set()
        assert plan.doors == []


class TestInteriorDoor:
    def test_xy_helper(self):
        d = InteriorDoor(x=3, y=4, side="north", feature="door_closed")
        assert d.xy == (3, 4)


class TestPartitionerConfigDisjointness:
    """Partitioners must respect the disjointness invariants from
    ``design/building_interiors.md``. SingleRoomPartitioner has
    trivial (empty) wall / corridor / door sets so the contract is
    vacuously held; other partitioners will re-run this suite."""

    def test_single_room_invariants(self):
        rect = Rect(1, 1, 6, 6)
        required = frozenset({(3, 3), (4, 4)})
        plan = SingleRoomPartitioner().plan(
            _cfg(rect, required_walkable=required),
        )
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)
        assert plan.interior_walls.isdisjoint(required)
        assert doors_xy.isdisjoint(required)

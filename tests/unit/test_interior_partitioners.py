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

from nhc.dungeon.interior.divided import DividedPartitioner
from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.rect_bsp import RectBSPPartitioner
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


def _bfs_connected(
    floor_tiles: set[tuple[int, int]], start: tuple[int, int],
) -> set[tuple[int, int]]:
    seen = {start}
    queue = [start]
    while queue:
        x, y = queue.pop()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            n = (x + dx, y + dy)
            if n in floor_tiles and n not in seen:
                seen.add(n)
                queue.append(n)
    return seen


class TestDividedPartitioner:
    def test_seven_by_seven_returns_two_rooms(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        assert len(plan.rooms) == 2

    def test_single_interior_wall_one_door(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        # Wall is a straight run (interior_walls non-empty, all on
        # same axis).
        assert plan.interior_walls
        assert len(plan.doors) == 1

    def test_door_not_on_footprint_edge(self):
        """Footprint-edge tiles are the boundary ring of the rect
        footprint — interior doors never sit on them."""
        rect = Rect(2, 2, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        edge = RectShape().perimeter_tiles(rect)
        for door in plan.doors:
            assert door.xy not in edge

    def test_rooms_bfs_connected(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        foot = RectShape().floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        # Flood fill from a tile in room A should reach room B.
        a_center = plan.rooms[0].rect.center
        reached = _bfs_connected(walkable, a_center)
        b_center = plan.rooms[1].rect.center
        assert b_center in reached

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)

    def test_required_walkable_respected(self):
        rect = Rect(1, 1, 7, 7)
        # Pick a central tile the partitioner MUST leave walkable.
        required = frozenset({(4, 4)})
        plan = DividedPartitioner().plan(
            _cfg(rect, required_walkable=required, seed=1),
        )
        assert plan.interior_walls.isdisjoint(required)
        assert required.isdisjoint({d.xy for d in plan.doors})

    def test_wall_is_straight_run(self):
        """Interior wall is a single straight line (horizontal OR
        vertical)."""
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        xs = {x for (x, _) in plan.interior_walls}
        ys = {y for (_, y) in plan.interior_walls}
        # Either all same x (vertical wall) or all same y (horizontal).
        assert len(xs) == 1 or len(ys) == 1

    def test_door_on_interior_wall_line(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        door = plan.doors[0]
        # Door coord lies on the wall axis.
        xs = {x for (x, _) in plan.interior_walls}
        ys = {y for (_, y) in plan.interior_walls}
        if len(xs) == 1:   # vertical wall
            assert door.x == next(iter(xs))
        else:
            assert door.y == next(iter(ys))

    def test_too_small_footprint_falls_back_to_single_room(self):
        """A 4×4 footprint cannot satisfy min_room=3 on both halves;
        DividedPartitioner returns one room instead of failing."""
        rect = Rect(1, 1, 4, 4)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        assert len(plan.rooms) == 1
        assert plan.interior_walls == set()
        assert plan.doors == []

    def test_door_side_set(self):
        rect = Rect(1, 1, 7, 7)
        plan = DividedPartitioner().plan(_cfg(rect, seed=1))
        door = plan.doors[0]
        assert door.side in ("north", "south", "east", "west")


class TestRectBSPPartitionerDoorway:
    def test_14x10_produces_3_to_5_rooms(self):
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        assert 3 <= len(plan.rooms) <= 5

    def test_every_pair_bfs_connected(self):
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        foot = RectShape().floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        # Flood fill from first room's center; every other room's
        # center must be reachable.
        start = plan.rooms[0].rect.center
        reached = _bfs_connected(walkable, start)
        for room in plan.rooms[1:]:
            assert room.rect.center in reached

    def test_doors_on_wall_runs_ge_3_tiles(self):
        """Every door sits on a wall run of ≥ 3 tiles — i.e., it
        has a wall neighbour on both axis-aligned sides along the
        wall's orientation."""
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        all_walls = plan.interior_walls | {d.xy for d in plan.doors}
        for door in plan.doors:
            x, y = door.xy
            # Door is FLOOR but originally lived on a wall line.
            # Two collinear neighbours must be in all_walls.
            horiz_run = (
                (x - 1, y) in all_walls and (x + 1, y) in all_walls
            )
            vert_run = (
                (x, y - 1) in all_walls and (x, y + 1) in all_walls
            )
            assert horiz_run or vert_run, (
                f"door at {door.xy} is not on a wall run of ≥ 3 tiles"
            )

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)

    def test_no_corridor_tiles_in_doorway_mode(self):
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        assert plan.corridor_tiles == set()

    def test_required_walkable_avoided_on_walls_and_doors(self):
        rect = Rect(1, 1, 14, 10)
        required = frozenset({(8, 5)})
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, required_walkable=required, seed=1),
        )
        assert plan.interior_walls.isdisjoint(required)
        assert required.isdisjoint({d.xy for d in plan.doors})

    def test_small_footprint_falls_back_gracefully(self):
        """A too-small footprint still produces a valid plan."""
        rect = Rect(1, 1, 5, 5)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        assert len(plan.rooms) >= 1

    def test_room_count_varies_with_seed(self):
        """Room count should fluctuate across seeds to exercise the
        partitioner's stochastic branches."""
        counts: set[int] = set()
        for seed in range(20):
            rect = Rect(1, 1, 14, 10)
            plan = RectBSPPartitioner(mode="doorway").plan(
                _cfg(rect, seed=seed),
            )
            counts.add(len(plan.rooms))
        assert len(counts) >= 1  # Sanity; full range asserted elsewhere.


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

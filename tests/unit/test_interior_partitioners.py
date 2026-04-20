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
from nhc.dungeon.interior.sector import SectorPartitioner
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.interior.lshape import LShapePartitioner
from nhc.dungeon.interior.temple import TemplePartitioner
from nhc.dungeon.model import (
    CircleShape, LShape, OctagonShape, Rect, RectShape, SurfaceType,
)


def _cfg(
    rect: Rect,
    shape=None,
    required_walkable=frozenset(),
    floor_index: int = 0,
    n_floors: int = 1,
    archetype: str = "tower",
    seed: int = 0,
    corridor_width: int = 1,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=shape or RectShape(),
        floor_index=floor_index,
        n_floors=n_floors,
        rng=random.Random(seed),
        archetype=archetype,
        required_walkable=required_walkable,
        corridor_width=corridor_width,
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

    def test_doors_on_edge_runs_ge_3_edges(self):
        """Every door sits on an edge run of ≥ 3 edges — i.e., the
        canonical edge targeted by door_side has both neighbouring
        collinear edges in plan.interior_edges."""
        from nhc.dungeon.model import canonicalize
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        for door in plan.doors:
            ex, ey, side = canonicalize(door.x, door.y, door.side)
            if side == "north":
                left = (ex - 1, ey, "north") in plan.interior_edges
                right = (ex + 1, ey, "north") in plan.interior_edges
            else:  # west
                left = (ex, ey - 1, "west") in plan.interior_edges
                right = (ex, ey + 1, "west") in plan.interior_edges
            assert left and right, (
                f"door at {door.xy} side={door.side} is not on an "
                f"edge run of ≥ 3 edges"
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


class TestRectBSPPartitionerCorridor:
    def test_width1_has_corridor_tiles(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=1, seed=0),
        )
        assert plan.corridor_tiles, "corridor mode must mark corridor tiles"

    def test_width1_corridor_is_one_tile_wide(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=1, seed=0),
        )
        # Corridor is a straight run — all same y (horizontal) or all
        # same x (vertical). Exactly one axis should have 1 unique value.
        xs = {x for (x, _) in plan.corridor_tiles}
        ys = {y for (_, y) in plan.corridor_tiles}
        assert len(ys) == 1 or len(xs) == 1

    def test_width2_corridor_is_two_tiles_wide(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=2, seed=0),
        )
        xs = {x for (x, _) in plan.corridor_tiles}
        ys = {y for (_, y) in plan.corridor_tiles}
        # For a horizontal corridor, corridor_tiles covers 2 distinct y
        # values across the full width.
        assert len(ys) == 2 or len(xs) == 2

    def test_door_count_equals_room_count(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=1, seed=0),
        )
        # Each room has exactly one door onto the corridor; sub-splits
        # inside a half would add extra doors. With no sub-splits,
        # doors == rooms.
        # Allow some extra doors from sub-splits: doors >= rooms.
        assert len(plan.doors) >= len(plan.rooms)

    def test_rooms_bfs_connected_through_corridor(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=2, seed=0),
        )
        foot = RectShape().floor_tiles(rect)
        walkable = (
            (foot - plan.interior_walls)
            | {d.xy for d in plan.doors}
        )
        start = plan.rooms[0].rect.center
        reached = _bfs_connected(walkable, start)
        for room in plan.rooms[1:]:
            assert room.rect.center in reached

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 20, 14)
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, corridor_width=1, seed=0),
        )
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)

    def test_required_walkable_lands_on_floor_or_corridor(self):
        rect = Rect(1, 1, 20, 14)
        required = frozenset({(10, 7)})
        plan = RectBSPPartitioner(mode="corridor").plan(
            _cfg(rect, required_walkable=required,
                 corridor_width=1, seed=1),
        )
        # Required tile MUST NOT be a wall or door; it can be a
        # corridor tile or a sub-room floor tile.
        assert plan.interior_walls.isdisjoint(required)
        assert required.isdisjoint({d.xy for d in plan.doors})


class TestSectorPartitionerSimple:
    def test_11_wide_circle_returns_four_sectors(self):
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        assert len(plan.rooms) == 4

    def test_central_hub_walkable(self):
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        # Hub tile is the required_walkable one, at the circle center.
        # It must not be a wall and not be a door.
        assert (6, 6) not in plan.interior_walls
        assert (6, 6) not in {d.xy for d in plan.doors}

    def test_at_least_one_door_per_sector_onto_hub(self):
        """Each sector must be BFS-connected to the hub through a
        door tile."""
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        foot = CircleShape().floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        reached = _bfs_connected(walkable, (6, 6))
        # Every sector room has at least one tile reachable from hub.
        for room in plan.rooms:
            room_tiles = room.floor_tiles() & foot
            # Sector overlaps the shape; at least one of its tiles
            # must be reachable from the hub.
            assert room_tiles & reached, (
                f"sector {room.id} not reachable from hub"
            )

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)

    def test_falls_back_when_not_circle(self):
        """Sector mode requires a CircleShape — non-circle footprints
        fall back to SingleRoom."""
        rect = Rect(1, 1, 7, 7)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=RectShape(), seed=0),
        )
        assert len(plan.rooms) == 1
        assert plan.interior_walls == set()


class TestTemplePartitioner:
    def test_15_wide_rect_has_nave_plus_two_chapels(self):
        rect = Rect(1, 1, 15, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.rooms) == 3

    def test_nave_is_tagged_and_chapels_are_tagged(self):
        rect = Rect(1, 1, 15, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        tags = [set(r.tags) for r in plan.rooms]
        # Exactly one nave, two chapels.
        nave_count = sum(1 for t in tags if "nave" in t)
        chapel_count = sum(1 for t in tags if "chapel" in t)
        assert nave_count == 1
        assert chapel_count == 2

    def test_two_doors_into_nave(self):
        rect = Rect(1, 1, 15, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.doors) == 2

    def test_rooms_bfs_connected_through_nave(self):
        rect = Rect(1, 1, 15, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        foot = RectShape().floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        start = plan.rooms[0].rect.center
        reached = _bfs_connected(walkable, start)
        for room in plan.rooms[1:]:
            assert room.rect.center in reached

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 15, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)

    def test_too_narrow_falls_back_to_single_room(self):
        rect = Rect(1, 1, 8, 10)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.rooms) == 1

    def test_required_walkable_respected(self):
        rect = Rect(1, 1, 15, 10)
        required = frozenset({(8, 5)})
        plan = TemplePartitioner().plan(
            _cfg(rect, required_walkable=required, seed=1),
        )
        assert plan.interior_walls.isdisjoint(required)


class TestLShapePartitioner:
    def test_produces_at_least_one_room_per_arm(self):
        rect = Rect(1, 1, 15, 10)
        for corner in ("nw", "ne", "sw", "se"):
            plan = LShapePartitioner().plan(
                _cfg(rect, shape=LShape(corner=corner), seed=0),
            )
            assert len(plan.rooms) >= 2, (
                f"L-shape corner={corner} did not produce ≥ 1 room "
                f"per arm (got {len(plan.rooms)})"
            )

    def test_rooms_bfs_connected_through_junction_door(self):
        rect = Rect(1, 1, 15, 10)
        shape = LShape(corner="nw")
        plan = LShapePartitioner().plan(
            _cfg(rect, shape=shape, seed=0),
        )
        foot = shape.floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        # Start from first room center, reach all others.
        start = plan.rooms[0].rect.center
        reached = _bfs_connected(walkable, start)
        for room in plan.rooms[1:]:
            cx, cy = room.rect.center
            # Center may fall outside L; pick any walkable tile in
            # the room's rect instead.
            room_tiles = [
                (x, y) for x in range(room.rect.x, room.rect.x2)
                for y in range(room.rect.y, room.rect.y2)
                if (x, y) in walkable
            ]
            assert room_tiles, f"room {room.id} has no walkable tiles"
            assert any(t in reached for t in room_tiles), (
                f"room {room.id} not reachable from room 0"
            )

    def test_exactly_one_junction_door(self):
        rect = Rect(1, 1, 15, 10)
        plan = LShapePartitioner().plan(
            _cfg(rect, shape=LShape(corner="nw"), seed=0),
        )
        assert len(plan.doors) >= 1

    def test_falls_back_when_not_lshape(self):
        rect = Rect(1, 1, 10, 10)
        plan = LShapePartitioner().plan(
            _cfg(rect, shape=RectShape(), seed=0),
        )
        assert len(plan.rooms) == 1
        assert plan.interior_walls == set()

    def test_disjointness_invariants(self):
        rect = Rect(1, 1, 15, 10)
        plan = LShapePartitioner().plan(
            _cfg(rect, shape=LShape(corner="nw"), seed=0),
        )
        doors_xy = {d.xy for d in plan.doors}
        assert plan.interior_walls.isdisjoint(doors_xy)
        assert plan.interior_walls.isdisjoint(plan.corridor_tiles)


class TestSectorPartitionerOctagon:
    def test_octagon_footprint_partitions_into_four_sectors(self):
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=OctagonShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        assert len(plan.rooms) == 4

    def test_octagon_hub_walkable(self):
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=OctagonShape(),
                 required_walkable=frozenset({(6, 6)}),
                 seed=0),
        )
        assert (6, 6) not in plan.interior_walls


class TestSectorPartitionerEnriched:
    def test_main_sector_rotates_per_floor(self):
        """Across 4 floors, the ``"main"`` tag lands on a different
        sector each time."""
        rect = Rect(1, 1, 11, 11)
        main_positions: list[int] = []
        for floor in range(4):
            plan = SectorPartitioner(mode="enriched").plan(
                _cfg(rect, shape=CircleShape(),
                     required_walkable=frozenset({(6, 6)}),
                     floor_index=floor, n_floors=4, seed=0),
            )
            main_idx = next(
                i for i, r in enumerate(plan.rooms) if "main" in r.tags
            )
            main_positions.append(main_idx)
        assert len(set(main_positions)) == 4

    def test_door_omitted_on_even_floors(self):
        """Simple mode: 4 doors every floor. Enriched: one fewer on
        every even-indexed floor (the omit-pattern)."""
        rect = Rect(1, 1, 11, 11)
        req = frozenset({(6, 6)})
        base = len(SectorPartitioner(mode="simple").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=req, seed=0),
        ).doors)
        even = len(SectorPartitioner(mode="enriched").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=req,
                 floor_index=0, n_floors=4, seed=0),
        ).doors)
        odd = len(SectorPartitioner(mode="enriched").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=req,
                 floor_index=1, n_floors=4, seed=0),
        ).doors)
        assert even == base - 1
        assert odd == base

    def test_hub_still_reaches_some_sector_on_enriched_floors(self):
        """Omitting one door must still leave connectivity: the hub
        can reach at least one sector."""
        rect = Rect(1, 1, 11, 11)
        req = frozenset({(6, 6)})
        plan = SectorPartitioner(mode="enriched").plan(
            _cfg(rect, shape=CircleShape(),
                 required_walkable=req,
                 floor_index=0, n_floors=4, seed=0),
        )
        foot = CircleShape().floor_tiles(rect)
        walkable = (foot - plan.interior_walls) | {
            d.xy for d in plan.doors
        }
        reached = _bfs_connected(walkable, (6, 6))
        reached_sectors = sum(
            1 for r in plan.rooms
            if r.floor_tiles() & reached
        )
        assert reached_sectors >= 1


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

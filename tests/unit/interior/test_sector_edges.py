"""SectorPartitioner emits edge walls via axis splits (M9).

Pie-slice geometry is replaced by axis-aligned splits through the
centre. Simple mode randomly picks one of {vert, horiz, cross};
enriched mode cycles deterministically by ``floor_index % 3``.
Edges are canonical and intersected with the footprint — no edge
dangles over VOID tiles.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.interior.sector import SectorPartitioner
from nhc.dungeon.model import (
    CircleShape, OctagonShape, Rect, RectShape, RoomShape,
    canonicalize,
)


def _cfg(
    rect: Rect,
    shape: RoomShape,
    required_walkable=frozenset(),
    seed: int = 0,
    floor_index: int = 0,
    n_floors: int = 1,
    min_room: int = 3,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=shape,
        floor_index=floor_index,
        n_floors=n_floors,
        rng=random.Random(seed),
        archetype="tower",
        required_walkable=required_walkable,
        min_room=min_room,
        padding=1,
        corridor_width=1,
    )


class TestSectorEdgesSimple:
    def test_emits_canonical_edges(self) -> None:
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, CircleShape(), seed=0),
        )
        assert plan.interior_edges
        for e in plan.interior_edges:
            assert e[2] in ("north", "west"), (
                f"edge {e} not canonical"
            )

    def test_room_count_in_expected_set(self) -> None:
        """Simple mode axis pick yields 2 or 4 rooms."""
        rect = Rect(1, 1, 11, 11)
        counts: set[int] = set()
        for seed in range(30):
            plan = SectorPartitioner(mode="simple").plan(
                _cfg(rect, CircleShape(), seed=seed),
            )
            counts.add(len(plan.rooms))
        assert counts <= {2, 4}, (
            f"sector produced unexpected room counts: {counts}"
        )

    def test_edges_touch_at_least_one_floor_tile(self) -> None:
        """Every canonical edge has at least one adjacent floor
        tile. Edges with one void side land at the building rim,
        where the partition meets the curved exterior wall (the
        reason a circular tower's bar-style interior wall now
        extends across the full diameter rather than stopping
        a tile short on each side)."""
        rect = Rect(1, 1, 11, 11)
        for seed in range(10):
            plan = SectorPartitioner(mode="simple").plan(
                _cfg(rect, CircleShape(), seed=seed),
            )
            foot = CircleShape().floor_tiles(rect)
            for (x, y, side) in plan.interior_edges:
                if side == "north":
                    a, b = (x, y - 1), (x, y)
                else:  # west
                    a, b = (x - 1, y), (x, y)
                assert a in foot or b in foot, (
                    f"seed={seed}: edge {(x, y, side)} sits in "
                    f"void on both sides "
                    f"(a={a} in={a in foot}, b={b} in={b in foot})"
                )

    def test_doors_target_canonical_edges(self) -> None:
        rect = Rect(1, 1, 11, 11)
        for seed in range(10):
            plan = SectorPartitioner(mode="simple").plan(
                _cfg(rect, CircleShape(), seed=seed),
            )
            for door in plan.doors:
                target = canonicalize(door.x, door.y, door.side)
                assert target in plan.interior_edges, (
                    f"seed={seed}: door at {door.xy} side="
                    f"{door.side} misses an edge"
                )

    def test_all_rooms_reachable_via_doors(self) -> None:
        rect = Rect(1, 1, 11, 11)
        for seed in range(10):
            plan = SectorPartitioner(mode="simple").plan(
                _cfg(rect, CircleShape(), seed=seed),
            )
            foot = CircleShape().floor_tiles(rect)
            door_edges = {
                canonicalize(d.x, d.y, d.side) for d in plan.doors
            }
            blocked = plan.interior_edges - door_edges

            from nhc.dungeon.model import edge_between
            from collections import deque
            # Seed BFS at a tile guaranteed to be in a room — the
            # first door's tile itself.
            start = plan.doors[0].xy
            seen = {start}
            queue = deque([start])
            while queue:
                x, y = queue.popleft()
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = (x + dx, y + dy)
                    if nb not in foot or nb in seen:
                        continue
                    if edge_between((x, y), nb) in blocked:
                        continue
                    seen.add(nb)
                    queue.append(nb)
            for room in plan.rooms:
                room_tiles = RectShape().floor_tiles(room.rect) & foot
                assert room_tiles & seen, (
                    f"seed={seed}: room {room.id} unreachable"
                )

    def test_octagon_also_works(self) -> None:
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, OctagonShape(), seed=0),
        )
        assert plan.interior_edges

    def test_falls_back_when_not_circle(self) -> None:
        rect = Rect(1, 1, 7, 7)
        plan = SectorPartitioner(mode="simple").plan(
            _cfg(rect, RectShape(), seed=0),
        )
        assert len(plan.rooms) == 1


class TestSectorEdgesEnriched:
    def test_axis_cycles_by_floor(self) -> None:
        """Enriched mode: floor 0 vertical (2 rooms), floor 1
        horizontal (2 rooms), floor 2 cross (4 rooms)."""
        rect = Rect(1, 1, 11, 11)
        room_counts: list[int] = []
        for floor in range(3):
            plan = SectorPartitioner(mode="enriched").plan(
                _cfg(
                    rect, CircleShape(),
                    floor_index=floor, n_floors=3, seed=0,
                ),
            )
            room_counts.append(len(plan.rooms))
        # Exactly two distinct room counts (2 and 4).
        assert set(room_counts) == {2, 4}, (
            f"expected axis rotation; got room counts {room_counts}"
        )

    def test_main_sector_tagged(self) -> None:
        rect = Rect(1, 1, 11, 11)
        plan = SectorPartitioner(mode="enriched").plan(
            _cfg(rect, CircleShape(), floor_index=0, seed=0),
        )
        mains = [r for r in plan.rooms if "main" in r.tags]
        assert len(mains) == 1

    def test_even_floor_omits_one_door(self) -> None:
        """On even floors, enriched drops one door."""
        rect = Rect(1, 1, 11, 11)
        # Use floor_index=2 (cross, even) vs floor_index=0 (vert,
        # even too — 1 door, omit -> 0 doors is degenerate).
        # Simpler: compare simple vs enriched at the same axis.
        simple = SectorPartitioner(mode="simple")
        enriched = SectorPartitioner(mode="enriched")

        # Force axis to cross for deterministic comparison: use
        # floor_index=2 under enriched which cycles to cross.
        enr_plan = enriched.plan(_cfg(
            rect, CircleShape(), floor_index=2, seed=0,
        ))
        # Compare with simple seeded to pick cross. Use many seeds
        # and find one with 4 rooms.
        base = None
        for seed in range(50):
            sim_plan = simple.plan(_cfg(
                rect, CircleShape(), seed=seed,
            ))
            if len(sim_plan.rooms) == 4:
                base = len(sim_plan.doors)
                break
        assert base is not None
        assert len(enr_plan.doors) == base - 1, (
            f"enriched cross on even floor should have base-1="
            f"{base - 1} doors; got {len(enr_plan.doors)}"
        )

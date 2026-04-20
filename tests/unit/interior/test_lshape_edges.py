"""LShapePartitioner emits edge walls (M8).

The junction wall along the inner corner becomes a canonical
edge run. Both arms already tile the L footprint, so no growth
is needed — the change is a 1:1 swap of wall tiles for edges.
The door tile sits on arm_b with ``door_side="north"`` targeting
the junction edge.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.lshape import LShapePartitioner
from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.model import LShape, Rect, canonicalize


def _cfg(
    rect: Rect,
    corner: str,
    required_walkable=frozenset(),
    seed: int = 0,
    min_room: int = 3,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=LShape(corner=corner),
        floor_index=0,
        n_floors=1,
        rng=random.Random(seed),
        archetype="mansion",
        required_walkable=required_walkable,
        min_room=min_room,
        padding=1,
        corridor_width=1,
    )


class TestLShapeEdges:
    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_emits_canonical_edges(self, corner: str) -> None:
        rect = Rect(0, 0, 9, 9)
        plan = LShapePartitioner().plan(
            _cfg(rect, corner=corner, seed=0),
        )
        # An L-shaped 9×9 may fall through to SingleRoom when the
        # arms don't meet min_room; pick the ones that split.
        if len(plan.rooms) == 1:
            pytest.skip(
                f"corner={corner}: fell through to SingleRoom"
            )
        assert plan.interior_edges
        for e in plan.interior_edges:
            assert e[2] in ("north", "west"), (
                f"corner={corner}: edge {e} not canonical"
            )

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_no_interior_wall_tiles(self, corner: str) -> None:
        rect = Rect(0, 0, 9, 9)
        plan = LShapePartitioner().plan(
            _cfg(rect, corner=corner, seed=0),
        )
        if len(plan.rooms) == 1:
            pytest.skip("fell through to SingleRoom")
        assert plan.interior_walls == set()

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_arms_tile_the_L_footprint(self, corner: str) -> None:
        rect = Rect(0, 0, 9, 9)
        shape = LShape(corner=corner)
        plan = LShapePartitioner().plan(
            _cfg(rect, corner=corner, seed=0),
        )
        if len(plan.rooms) == 1:
            pytest.skip("fell through to SingleRoom")
        foot = shape.floor_tiles(rect)
        from nhc.dungeon.model import RectShape
        covered: set[tuple[int, int]] = set()
        for room in plan.rooms:
            covered |= RectShape().floor_tiles(room.rect)
        assert covered == foot, (
            f"corner={corner}: missing={foot - covered}, "
            f"extra={covered - foot}"
        )

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_door_targets_canonical_edge(
        self, corner: str,
    ) -> None:
        rect = Rect(0, 0, 9, 9)
        plan = LShapePartitioner().plan(
            _cfg(rect, corner=corner, seed=0),
        )
        if len(plan.rooms) == 1:
            pytest.skip("fell through to SingleRoom")
        assert len(plan.doors) == 1
        door = plan.doors[0]
        target = canonicalize(door.x, door.y, door.side)
        assert target in plan.interior_edges, (
            f"corner={corner}: door at {door.xy} side={door.side} "
            f"does not target an emitted edge"
        )

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_arms_reachable_via_door(self, corner: str) -> None:
        rect = Rect(0, 0, 9, 9)
        shape = LShape(corner=corner)
        plan = LShapePartitioner().plan(
            _cfg(rect, corner=corner, seed=0),
        )
        if len(plan.rooms) == 1:
            pytest.skip("fell through to SingleRoom")
        foot = shape.floor_tiles(rect)
        door = plan.doors[0]
        door_edge = canonicalize(door.x, door.y, door.side)
        blocked = plan.interior_edges - {door_edge}

        from nhc.dungeon.model import edge_between
        from collections import deque
        start = plan.rooms[0].rect.center
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
        for room in plan.rooms[1:]:
            assert room.rect.center in seen, (
                f"corner={corner}: room {room.id} unreachable"
            )

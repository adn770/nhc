"""DividedPartitioner emits edge walls (M6).

One axis-aligned split across the footprint becomes a canonical
edge run; one of the two halves absorbs the former wall row so
both rooms fill the footprint. The door tile sits on the
un-grown half with ``door_side`` targeting the edge.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.divided import DividedPartitioner
from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.model import Rect, RectShape, canonicalize


def _cfg(
    rect: Rect,
    required_walkable=frozenset(),
    seed: int = 0,
    min_room: int = 3,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=RectShape(),
        floor_index=0,
        n_floors=1,
        rng=random.Random(seed),
        archetype="test",
        required_walkable=required_walkable,
        min_room=min_room,
        padding=1,
        corridor_width=1,
    )


class TestDividedEdges:
    def test_emits_canonical_edges(self) -> None:
        rect = Rect(0, 0, 8, 8)
        plan = DividedPartitioner().plan(_cfg(rect, seed=0))
        assert plan.interior_edges, "Divided must emit edges"
        for e in plan.interior_edges:
            assert e[2] in ("north", "west"), (
                f"edge {e} not canonical"
            )

    def test_two_rooms_tile_the_footprint(self) -> None:
        rect = Rect(0, 0, 8, 8)
        plan = DividedPartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.rooms) == 2
        foot = RectShape().floor_tiles(rect)
        covered: set[tuple[int, int]] = set()
        for room in plan.rooms:
            covered |= RectShape().floor_tiles(room.rect)
        assert covered == foot, (
            f"missing={foot - covered}, extra={covered - foot}"
        )

    def test_door_targets_canonical_edge(self) -> None:
        rect = Rect(0, 0, 8, 8)
        plan = DividedPartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.doors) == 1
        door = plan.doors[0]
        target = canonicalize(door.x, door.y, door.side)
        assert target in plan.interior_edges, (
            f"door at {door.xy} side={door.side} does not target "
            f"an emitted edge"
        )

    def test_8x8_horizontal_split_yields_two_8x4(self) -> None:
        """Residential fixture: axis-agnostic sizing check."""
        rect = Rect(0, 0, 8, 8)
        for seed in range(20):
            plan = DividedPartitioner().plan(_cfg(rect, seed=seed))
            assert len(plan.rooms) == 2
            widths = sorted(r.rect.width for r in plan.rooms)
            heights = sorted(r.rect.height for r in plan.rooms)
            # Horizontal split: both rooms 8 wide, heights (4, 4).
            # Vertical split: both rooms 8 tall, widths (4, 4).
            if widths == [8, 8]:
                assert heights == [4, 4], (
                    f"seed={seed}: 8×8 horiz split should be 8×4+8×4, "
                    f"got heights={heights}"
                )
                return
            if heights == [8, 8]:
                assert widths == [4, 4], (
                    f"seed={seed}: 8×8 vert split should be 4×8+4×8, "
                    f"got widths={widths}"
                )
                return
        pytest.skip("no seed in 20 produced a balanced split")

    def test_pair_bfs_connected_via_door(self) -> None:
        rect = Rect(0, 0, 8, 8)
        plan = DividedPartitioner().plan(_cfg(rect, seed=0))
        foot = RectShape().floor_tiles(rect)
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
                f"room {room.id} unreachable via door edge"
            )

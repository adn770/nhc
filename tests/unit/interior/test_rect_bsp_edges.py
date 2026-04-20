"""RectBSPPartitioner doorway mode emits edge walls (M4).

Every split produces a canonical edge run; rooms grow into the
old wall row (a 9×8 footprint now yields two 9×4 rooms instead
of 9×3 + wall + 9×4). Doors stay as tile features with
``door_side`` suppressing the edge beneath them.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.interior.rect_bsp import RectBSPPartitioner
from nhc.dungeon.model import Rect, RectShape, canonicalize
import random


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


class TestRectBSPDoorwayEdges:
    def test_emits_canonical_edges(self) -> None:
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        assert plan.interior_edges, (
            "doorway mode must produce at least one edge"
        )
        for e in plan.interior_edges:
            assert e[2] in ("north", "west"), (
                f"edge {e} is not canonical"
            )

    def test_no_interior_wall_tiles(self) -> None:
        """After M4, doorway mode produces no WALL tile entries."""
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        assert plan.interior_walls == set()

    def test_rooms_cover_full_footprint(self) -> None:
        """Leaves grow to fill the old wall rows; every footprint
        tile lives in exactly one room."""
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        foot = RectShape().floor_tiles(rect)
        covered: set[tuple[int, int]] = set()
        for room in plan.rooms:
            covered |= RectShape().floor_tiles(room.rect)
        assert covered == foot, (
            f"rooms missed tiles: {foot - covered}"
        )
        # Room rects must not overlap (leaves are disjoint by
        # construction).
        rect_tiles: list[set[tuple[int, int]]] = [
            RectShape().floor_tiles(r.rect) for r in plan.rooms
        ]
        for i, a in enumerate(rect_tiles):
            for b in rect_tiles[i + 1:]:
                assert a.isdisjoint(b), (
                    "leaves must not overlap"
                )

    def test_doors_sit_on_edge_run(self) -> None:
        """Each door's door_side points at a canonical edge that
        is in the interior_edges set."""
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        for door in plan.doors:
            target = canonicalize(door.x, door.y, door.side)
            assert target in plan.interior_edges, (
                f"door at {door.xy} side={door.side} does not "
                f"target an emitted edge"
            )

    def test_every_pair_bfs_connected_via_doors(self) -> None:
        """Leaves are reachable from each other by stepping
        through door tiles (tiles are walkable; the engine
        suppresses the edge beneath an open door)."""
        rect = Rect(1, 1, 14, 10)
        plan = RectBSPPartitioner(mode="doorway").plan(
            _cfg(rect, seed=0),
        )
        # Build adjacency: every footprint tile is walkable, but
        # stepping across a canonical edge is blocked unless a
        # door tile sits on it.
        foot = RectShape().floor_tiles(rect)
        door_edges = {
            canonicalize(d.x, d.y, d.side) for d in plan.doors
        }
        blocked_edges = plan.interior_edges - door_edges

        def step_ok(a, b):
            from nhc.dungeon.model import edge_between
            return edge_between(a, b) not in blocked_edges

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
                if not step_ok((x, y), nb):
                    continue
                seen.add(nb)
                queue.append(nb)
        for room in plan.rooms[1:]:
            assert room.rect.center in seen, (
                f"room {room.id} unreachable via door edges"
            )

    def test_9x8_splits_into_equal_rooms(self) -> None:
        """The user's motivating example: 9×8 building splits on
        a single row, yielding two 9×4 rooms."""
        rect = Rect(0, 0, 9, 8)
        # A seed that produces a single horizontal split.
        for seed in range(30):
            plan = RectBSPPartitioner(mode="doorway").plan(
                _cfg(rect, seed=seed),
            )
            if len(plan.rooms) == 2:
                heights = sorted(r.rect.height for r in plan.rooms)
                widths = sorted(r.rect.width for r in plan.rooms)
                # Either horizontal split (9×4 + 9×4) or vertical
                # (5×8 + 4×8 or similar).
                if widths == [9, 9]:
                    assert heights == [4, 4], (
                        f"seed={seed}: 9×8 horizontal split should "
                        f"yield two 9×4 rooms, got heights={heights}"
                    )
                    return
        pytest.skip(
            "no seed in 30 produced a 2-room horizontal split; "
            "partitioner may favour more rooms or vertical splits"
        )

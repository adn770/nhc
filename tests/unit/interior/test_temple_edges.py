"""TemplePartitioner emits edge walls (M7).

Two parallel walls separating the nave from its flanking chapels
become two canonical edge runs. Each chapel absorbs its wall
row/column so the three rooms tile the footprint. Two doors on
the nave side connect nave to chapels.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.interior.temple import TemplePartitioner
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
        archetype="temple",
        required_walkable=required_walkable,
        min_room=min_room,
        padding=1,
        corridor_width=1,
    )


class TestTempleEdges:
    def test_emits_canonical_edges(self) -> None:
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert plan.interior_edges
        for e in plan.interior_edges:
            assert e[2] in ("north", "west"), (
                f"edge {e} not canonical"
            )

    def test_no_interior_wall_tiles(self) -> None:
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert plan.interior_walls == set()

    def test_three_rooms_tile_the_footprint(self) -> None:
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.rooms) == 3
        foot = RectShape().floor_tiles(rect)
        covered: set[tuple[int, int]] = set()
        for room in plan.rooms:
            covered |= RectShape().floor_tiles(room.rect)
        assert covered == foot, (
            f"missing={foot - covered}, extra={covered - foot}"
        )

    def test_two_edge_runs(self) -> None:
        """Exactly two parallel edge runs along the same axis."""
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        norths = {e for e in plan.interior_edges if e[2] == "north"}
        wests = {e for e in plan.interior_edges if e[2] == "west"}
        # Either all north (horizontal runs) or all west (vertical).
        assert bool(norths) ^ bool(wests), (
            "edge runs must all share an axis"
        )
        if norths:
            ys = {y for (_, y, _) in norths}
            assert len(ys) == 2, f"expected 2 runs, got ys={ys}"
        else:
            xs = {x for (x, _, _) in wests}
            assert len(xs) == 2, f"expected 2 runs, got xs={xs}"

    def test_two_doors_target_canonical_edges(self) -> None:
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        assert len(plan.doors) == 2
        for door in plan.doors:
            target = canonicalize(door.x, door.y, door.side)
            assert target in plan.interior_edges, (
                f"door at {door.xy} side={door.side} does not "
                f"target an emitted edge"
            )

    def test_nave_reachable_from_both_chapels(self) -> None:
        rect = Rect(0, 0, 14, 14)
        plan = TemplePartitioner().plan(_cfg(rect, seed=0))
        nave = next(r for r in plan.rooms if "nave" in r.tags)
        chapels = [r for r in plan.rooms if "chapel" in r.tags]
        assert len(chapels) == 2

        foot = RectShape().floor_tiles(rect)
        door_edges = {
            canonicalize(d.x, d.y, d.side) for d in plan.doors
        }
        blocked = plan.interior_edges - door_edges

        from nhc.dungeon.model import edge_between
        from collections import deque
        start = nave.rect.center
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
        for chapel in chapels:
            assert chapel.rect.center in seen, (
                f"chapel {chapel.id} unreachable from nave"
            )

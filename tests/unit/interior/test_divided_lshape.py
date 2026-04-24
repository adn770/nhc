"""DividedPartitioner must respect LShape footprints.

Same bug class as :mod:`test_rect_bsp_lshape`: cottage /
residential / farm_main / tower_square archetypes include ``"l"``
in their ``shape_pool`` but :class:`DividedPartitioner` picked a
split axis on the bounding rect only. When the split ran through
the notch, the door could land in the notch and the two halves
became disconnected after the shell stamped walls.

Pin the same invariants here — doors inside the footprint, rooms
reachable from each other via the door.
"""

from __future__ import annotations

import random
from collections import deque

import pytest

from nhc.dungeon.interior.divided import DividedPartitioner
from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.model import (
    LShape, Rect, RectShape, canonicalize, edge_between,
)


_COTTAGE_RECTS = [Rect(0, 0, 9, 9), Rect(0, 0, 10, 8), Rect(0, 0, 8, 10)]
_SEED_RANGE = range(50)


def _cfg(rect: Rect, corner: str, seed: int) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=LShape(corner=corner),
        floor_index=0,
        n_floors=1,
        rng=random.Random(seed),
        archetype="cottage",
        min_room=3,
        padding=1,
        corridor_width=1,
    )


def _reachable_from(
    start: tuple[int, int],
    foot: set[tuple[int, int]],
    blocked_edges: set[tuple[int, int, str]],
) -> set[tuple[int, int]]:
    seen = {start}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nb = (x + dx, y + dy)
            if nb not in foot or nb in seen:
                continue
            if edge_between((x, y), nb) in blocked_edges:
                continue
            seen.add(nb)
            queue.append(nb)
    return seen


class TestDividedLShape:
    @pytest.mark.parametrize("rect", _COTTAGE_RECTS)
    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_doors_inside_lshape_footprint(
        self, corner: str, rect: Rect,
    ) -> None:
        shape = LShape(corner=corner)
        foot = shape.floor_tiles(rect)
        for seed in _SEED_RANGE:
            plan = DividedPartitioner().plan(
                _cfg(rect, corner, seed),
            )
            for door in plan.doors:
                assert door.xy in foot, (
                    f"seed={seed} corner={corner} rect={rect}: "
                    f"door at {door.xy} falls in the L-shape notch"
                )

    @pytest.mark.parametrize("rect", _COTTAGE_RECTS)
    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_rooms_reachable_via_door(
        self, corner: str, rect: Rect,
    ) -> None:
        shape = LShape(corner=corner)
        foot = shape.floor_tiles(rect)
        for seed in _SEED_RANGE:
            plan = DividedPartitioner().plan(
                _cfg(rect, corner, seed),
            )
            door_edges = {
                canonicalize(d.x, d.y, d.side) for d in plan.doors
            }
            blocked = plan.interior_edges - door_edges
            # Find a footprint tile in the first room to BFS from.
            first_foot = (
                RectShape().floor_tiles(plan.rooms[0].rect) & foot
            )
            if not first_foot:
                # Would be caught by a separate invariant but tell
                # the user here too — no floor in the start room.
                pytest.fail(
                    f"seed={seed} corner={corner} rect={rect}: "
                    f"first room has no footprint floor"
                )
            reachable = _reachable_from(
                next(iter(first_foot)), foot, blocked,
            )
            for room in plan.rooms[1:]:
                room_foot = (
                    RectShape().floor_tiles(room.rect) & foot
                )
                if not room_foot:
                    continue
                assert room_foot & reachable, (
                    f"seed={seed} corner={corner} rect={rect}: "
                    f"room {room.id} unreachable from first room"
                )

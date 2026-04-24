"""RectBSPPartitioner must respect LShape footprints.

Regression: tavern / inn / training / keep / mansion archetypes
include ``"l"`` in their ``shape_pool`` but the rect-BSP splitter
partitioned the bounding rect only. When the L-shape notch
landed inside one of the resulting leaves, the leaf's floor
tiles were half-swallowed by the shell's perimeter wall pass
and BSP's split-wall doors could fall in the notch -- stranding
whole rooms (including the floor's stairs).

Debug bundle on site_7_9_b8 (inn, L-shape SE corner): five
rooms; the stairs_up tile sat in a Room that was only connected
through a door placed inside the notch. Player could not reach
the stairs.

These tests pin the invariants every L-shape partition must
satisfy:

- Every door tile is inside the L footprint.
- Every room has at least one floor tile inside the footprint.
- Every room is reachable via open doors from any other room
  (walking through floor tiles only).
"""

from __future__ import annotations

import random
from collections import deque

import pytest

from nhc.dungeon.interior.protocol import PartitionerConfig
from nhc.dungeon.interior.rect_bsp import RectBSPPartitioner
from nhc.dungeon.model import (
    LShape, Rect, RectShape, canonicalize, edge_between,
)


_INN_RECT = Rect(0, 0, 16, 13)
_SEED_RANGE = range(50)


def _cfg(
    rect: Rect, corner: str, seed: int,
    min_room: int = 3,
) -> PartitionerConfig:
    return PartitionerConfig(
        footprint=rect,
        shape=LShape(corner=corner),
        floor_index=0,
        n_floors=1,
        rng=random.Random(seed),
        archetype="inn",
        min_room=min_room,
        padding=1,
        corridor_width=1,
    )


def _room_foot(room_rect: Rect, foot: set[tuple[int, int]]) -> set:
    return RectShape().floor_tiles(room_rect) & foot


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


class TestRectBSPLShape:
    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_doors_inside_lshape_footprint(
        self, corner: str,
    ) -> None:
        shape = LShape(corner=corner)
        foot = shape.floor_tiles(_INN_RECT)
        for seed in _SEED_RANGE:
            plan = RectBSPPartitioner(mode="doorway").plan(
                _cfg(_INN_RECT, corner, seed),
            )
            for door in plan.doors:
                assert door.xy in foot, (
                    f"seed={seed} corner={corner}: door at "
                    f"{door.xy} falls inside the L-shape notch "
                    f"(notch will become VOID/WALL after shell "
                    f"pass, stranding the door)"
                )

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_every_room_has_footprint_floor(
        self, corner: str,
    ) -> None:
        shape = LShape(corner=corner)
        foot = shape.floor_tiles(_INN_RECT)
        for seed in _SEED_RANGE:
            plan = RectBSPPartitioner(mode="doorway").plan(
                _cfg(_INN_RECT, corner, seed),
            )
            for room in plan.rooms:
                room_foot = _room_foot(room.rect, foot)
                assert room_foot, (
                    f"seed={seed} corner={corner}: room "
                    f"{room.id} has no floor tile inside the "
                    f"L-shape footprint (rect={room.rect} lies "
                    f"entirely in the notch)"
                )

    @pytest.mark.parametrize("corner", ["nw", "ne", "sw", "se"])
    def test_all_rooms_reachable_via_doors(
        self, corner: str,
    ) -> None:
        shape = LShape(corner=corner)
        foot = shape.floor_tiles(_INN_RECT)
        for seed in _SEED_RANGE:
            plan = RectBSPPartitioner(mode="doorway").plan(
                _cfg(_INN_RECT, corner, seed),
            )
            door_edges = {
                canonicalize(d.x, d.y, d.side) for d in plan.doors
            }
            blocked = plan.interior_edges - door_edges
            first_room_foot = _room_foot(plan.rooms[0].rect, foot)
            assert first_room_foot, (
                f"seed={seed} corner={corner}: first room has no "
                f"footprint floor — earlier invariant should have "
                f"caught this"
            )
            start = next(iter(first_room_foot))
            reachable = _reachable_from(start, foot, blocked)
            for room in plan.rooms[1:]:
                room_foot = _room_foot(room.rect, foot)
                assert room_foot & reachable, (
                    f"seed={seed} corner={corner}: room "
                    f"{room.id} is unreachable from the start "
                    f"room via open doors (room_foot={room_foot})"
                )

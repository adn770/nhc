"""Shop locked-door BSP-leaf picker (C4).

Shops route through RectBSPPartitioner in doorway mode (via C3),
so a shop floor has ≥ 3 rooms (BSP leaves). The locked-door rule
says: lock the door that leads into the smallest leaf, with a
deterministic tie-break on equal areas. That picker lives in
:func:`nhc.dungeon.sites._placement.smallest_leaf_door` and is
called from ``_lock_shop_doors``.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.building import Building
from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, Terrain, Tile,
)
from nhc.dungeon.sites._placement import smallest_leaf_door
from nhc.dungeon.sites.town import assemble_town


def _make_shop_fixture() -> tuple[Level, Building]:
    """Build a 10x8 shop fixture with 4 rectangular rooms.

    Room A (big):    (1, 1) - (5, 5) — 4x4
    Room B (medium): (6, 1) - (8, 3) — 2x2
    Room C (small):  (6, 4) - (8, 5) — 2x1   <-- smallest
    Room D (medium): (1, 6) - (8, 6) — 7x0   (1-tall strip)

    Doors are placed between neighbour pairs. The smallest room C
    is adjacent to the door at (6, 4).
    """
    tiles = [
        [Tile(terrain=Terrain.VOID) for _ in range(10)]
        for _ in range(8)
    ]
    # Fill 1..8, 1..6 as FLOOR.
    for y in range(1, 7):
        for x in range(1, 9):
            tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    # Interior walls.
    for y in range(1, 7):
        tiles[y][5] = Tile(terrain=Terrain.WALL)      # A | (B/C)
    for x in range(5, 9):
        tiles[3][x] = Tile(terrain=Terrain.WALL)      # B | C
    for x in range(1, 9):
        tiles[5][x] = Tile(terrain=Terrain.WALL)      # top | D
    # Doors between neighbour rooms.
    tiles[2][5] = Tile(terrain=Terrain.FLOOR, feature="door_closed")
    tiles[3][6] = Tile(terrain=Terrain.FLOOR, feature="door_closed")
    # Door between A and D (floor-5 wall).
    tiles[5][2] = Tile(terrain=Terrain.FLOOR, feature="door_closed")

    level = Level(
        id="shop_f0", name="shop_f0", depth=1,
        width=10, height=8, tiles=tiles,
        building_id="shop",
    )
    level.rooms = [
        Room(id="A", rect=Rect(1, 1, 4, 4), shape=RectShape()),
        Room(id="B", rect=Rect(6, 1, 3, 2), shape=RectShape()),
        Room(id="C", rect=Rect(6, 4, 3, 1), shape=RectShape()),
        Room(id="D", rect=Rect(1, 6, 8, 1), shape=RectShape()),
    ]
    building = Building(
        id="shop", base_shape=RectShape(),
        base_rect=Rect(1, 1, 8, 6),
        floors=[level],
    )
    return level, building


class TestSmallestLeafDoor:
    def test_picks_door_adjacent_to_smallest_room(self) -> None:
        level, building = _make_shop_fixture()
        door = smallest_leaf_door(level, building)
        assert door is not None
        # Room C is smallest (3 tiles). The only interior door
        # adjacent to C is (6, 3) — the one between B and C.
        assert door == (6, 3)

    def test_deterministic_tie_break(self) -> None:
        """Two rooms of equal size must always yield the same door
        across runs — the picker sorts candidates rather than
        relying on dict / set iteration order."""
        level, building = _make_shop_fixture()
        # Shrink room D to match room C's size so they tie at 3
        # tiles. The tie-break should fall on the lexicographically
        # smallest room.rect.
        level.rooms[-1] = Room(
            id="D_tied", rect=Rect(1, 6, 3, 1), shape=RectShape(),
        )
        first = smallest_leaf_door(level, building)
        second = smallest_leaf_door(level, building)
        assert first == second

    def test_returns_none_when_no_interior_doors(self) -> None:
        level, building = _make_shop_fixture()
        for row in level.tiles:
            for t in row:
                if t.feature == "door_closed":
                    t.feature = None
        assert smallest_leaf_door(level, building) is None


class TestLockedDoorOnSmallestLeaf:
    """Integration: for every seed that produces a locked shop
    door, that door must be adjacent to the shop's smallest
    room."""

    def test_locked_door_adjacent_to_smallest_room(self) -> None:
        checked = 0
        for seed in range(200):
            site = assemble_town(
                "t1", random.Random(seed), size_class="village",
            )
            for b in site.buildings:
                if "shop" not in b.ground.rooms[0].tags:
                    continue
                locked = [
                    (x, y)
                    for y, row in enumerate(b.ground.tiles)
                    for x, t in enumerate(row)
                    if t.feature == "door_locked"
                ]
                if not locked:
                    continue
                # Smallest room by floor-tile count.
                smallest = min(
                    b.ground.rooms,
                    key=lambda r: (
                        len(r.floor_tiles()),
                        r.rect.x, r.rect.y,
                        r.rect.width, r.rect.height,
                    ),
                )
                floor_tiles = smallest.floor_tiles()
                for (lx, ly) in locked:
                    assert any(
                        (lx + dx, ly + dy) in floor_tiles
                        for dx, dy in [
                            (-1, 0), (1, 0), (0, -1), (0, 1),
                        ]
                    ), (
                        f"seed={seed}: locked door ({lx},{ly}) on "
                        f"{b.id} is not adjacent to smallest room "
                        f"{smallest.id} rect={smallest.rect}"
                    )
                    checked += 1
        assert checked > 0, (
            "no seed in 200 produced a locked shop door to check"
        )

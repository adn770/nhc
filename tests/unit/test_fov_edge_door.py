"""Tests for FOV when player stands ON a closed edge-door.

Layout (7×7):

     0123456
  0  #######
  1  ###.###    corridor: (3,1)
  2  ###D###    closed door: (3,2) door_side="south" ← player
  3  #.....#    room row
  4  #.....#    room row
  5  #.....#    room row
  6  #######

The player stands on the door tile (3,2). The door faces south,
meaning the room is to the south. With edge-door FOV blocking,
no tile in the room should be visible — neither directly south
nor diagonally (the diagonal leak is the bug being fixed).
"""

from __future__ import annotations

import pytest

from nhc.dungeon.model import Level, Terrain, Tile
from nhc.utils.fov import compute_fov

WIDTH, HEIGHT = 7, 7
FOV_RADIUS = 8

PLAYER = (3, 2)   # on the closed door tile
DOOR_SIDE = "south"

# Tiles that must NOT be visible (room beyond the closed door)
ROOM_TILES = [
    (x, y) for y in range(3, 6) for x in range(1, 6)
]

# Tiles that MUST be visible (corridor behind the player)
CORRIDOR_TILE = (3, 1)


def _build_level() -> Level:
    """Build a corridor-door-room layout."""
    level = Level.create_empty("test", "Test", depth=1,
                               width=WIDTH, height=HEIGHT)
    # Fill everything as WALL first
    for y in range(HEIGHT):
        for x in range(WIDTH):
            level.tiles[y][x] = Tile(terrain=Terrain.WALL)

    # Corridor at (3,1)
    level.tiles[1][3] = Tile(terrain=Terrain.FLOOR, is_corridor=True)

    # Door at (3,2) — closed, south-facing
    level.tiles[2][3] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="south",
    )

    # Room: cols 1-5, rows 3-5
    for y in range(3, 6):
        for x in range(1, 6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    return level


def _fov_with_edge_blocking(
    level: Level, px: int, py: int,
) -> set[tuple[int, int]]:
    """Compute FOV replicating Game._update_fov edge-door logic."""
    from nhc.core.game import edge_door_blocked_tiles

    cur = level.tile_at(px, py)
    blocked: set[tuple[int, int]] = set()
    if (cur and cur.feature in ("door_closed", "door_locked",
                                "door_secret")
            and cur.door_side):
        blocked = edge_door_blocked_tiles(px, py, cur.door_side)

    def is_blocking(x: int, y: int) -> bool:
        if (x, y) in blocked:
            return True
        tile = level.tile_at(x, y)
        if not tile:
            return True
        return tile.blocks_sight

    visible = compute_fov(px, py, FOV_RADIUS, is_blocking)
    # Virtual wall tiles are room floor, not actual walls —
    # exclude them so the room isn't partially revealed.
    visible -= blocked
    return visible


class TestEdgeDoorSouthBlocking:
    """Player on south-facing closed door: room must not be visible."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_level()
        return _fov_with_edge_blocking(level, *PLAYER)

    def test_corridor_visible(self, fov):
        assert CORRIDOR_TILE in fov, (
            "corridor behind player should be visible"
        )

    @pytest.mark.parametrize("tile", ROOM_TILES,
                             ids=[f"({x},{y})" for x, y in ROOM_TILES])
    def test_room_tile_not_visible(self, fov, tile):
        assert tile not in fov, (
            f"room tile {tile} visible through closed south door"
        )


# ── Same test for each cardinal direction ────────────────────


def _build_east_door_level() -> Level:
    """Corridor west, east-facing door, room to the east.

         0123456
      0  #######
      1  #.D...#    corridor:(1,1) door:(2,1) room:(3-5,1)
      2  #######
    (simplified: 1-tile high corridor + room, taller would work too)

    Use a 7×7 level with a 3-tall corridor and room for proper
    FOV testing.

         0123456
      0  #######
      1  ##.####    corridor: (2,1)
      2  #.D...#    door:(2,2) side="east", corridor:(1,2)
      3  ##.####    corridor: (2,3)
      4  #######
    """
    level = Level.create_empty("test", "Test", depth=1,
                               width=7, height=5)
    for y in range(5):
        for x in range(7):
            level.tiles[y][x] = Tile(terrain=Terrain.WALL)

    # Corridor column at x=1, rows 1-3
    for y in range(1, 4):
        level.tiles[y][1] = Tile(terrain=Terrain.FLOOR,
                                 is_corridor=True)

    # Door at (2,2) — east-facing
    level.tiles[2][2] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="east",
    )

    # Room: cols 3-5, rows 1-3
    for y in range(1, 4):
        for x in range(3, 6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    return level


EAST_DOOR_PLAYER = (2, 2)
EAST_ROOM_TILES = [
    (x, y) for y in range(1, 4) for x in range(3, 6)
]


class TestEdgeDoorEastBlocking:
    """Player on east-facing closed door: room to east not visible."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_east_door_level()
        return _fov_with_edge_blocking(level, *EAST_DOOR_PLAYER)

    def test_corridor_visible(self, fov):
        assert (1, 2) in fov, (
            "corridor behind player should be visible"
        )

    @pytest.mark.parametrize(
        "tile", EAST_ROOM_TILES,
        ids=[f"({x},{y})" for x, y in EAST_ROOM_TILES],
    )
    def test_room_tile_not_visible(self, fov, tile):
        assert tile not in fov, (
            f"room tile {tile} visible through closed east door"
        )

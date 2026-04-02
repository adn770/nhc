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

from nhc.core.game import (
    compute_hatch_clear, door_wall_run_hidden, edge_door_blocked_tiles,
)
from nhc.dungeon.model import Level, OctagonShape, Rect, Room, Terrain, Tile
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


# ── Wall-run hiding: room walls near closed doors ────────────
#
# Rules:
#   1. A wall tile in a door's wall run should be HIDDEN if it
#      has no visible FLOOR neighbor (excluding the door tile).
#      This prevents room structure leaking to the player.
#   2. A wall tile that IS adjacent to a visible FLOOR tile
#      (e.g. the player's own corridor) should remain VISIBLE —
#      it is part of the player's known surroundings.
#   3. The entire contiguous wall run is walked, not just ±1.
#   4. Once a wall tile with a visible FLOOR neighbor is found,
#      the walk stops in that direction (the rest is corridor).


def _fov_with_wall_run_hiding(
    level: Level, px: int, py: int,
) -> set[tuple[int, int]]:
    """Compute FOV with both edge-door blocking and wall-run hiding."""
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
    visible -= blocked

    hidden = door_wall_run_hidden(level, visible)
    visible -= hidden

    return visible


# ── Scenario A: isolated room wall (no corridor alongside) ──
#
# The wall tiles flanking the door have NO visible floor
# neighbor, so they must be hidden.
#
#      0 1 2 3 4 5 6 7 8
#  0   . . . . . . . . .    VOID
#  1   . . . # # # # . .    room north wall
#  2   . . . # . . # . .    room interior
#  3   . . . # . . # . .    room interior
#  4   . . . # D . # . .    door at (4,4) side="west"
#  5   . . . # . . # . .    room interior
#  6   . . . # # # # . .    room south wall
#  7   . . . . . . . . .    VOID
#  8   . . # . . . . . .    corridor
#  9   . . # # # # . . .    corridor wall
#
# Player at (3,4), one tile west of the door.
# Wall tiles (4,3) and (4,5) have no visible floor neighbor
# (room interior not visible, VOID on the corridor side).


def _build_isolated_room_west_door() -> Level:
    level = Level.create_empty("test", "Test", depth=1,
                               width=9, height=10)
    # Everything starts as VOID (from create_empty)

    # Room walls (x=3 and x=6, y=1-6; y=1 and y=6, x=3-6)
    for y in range(1, 7):
        level.tiles[y][3] = Tile(terrain=Terrain.WALL)
        level.tiles[y][6] = Tile(terrain=Terrain.WALL)
    for x in range(3, 7):
        level.tiles[1][x] = Tile(terrain=Terrain.WALL)
        level.tiles[6][x] = Tile(terrain=Terrain.WALL)

    # Room interior
    for y in range(2, 6):
        for x in range(4, 6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    # Door at (4,4) — west edge
    # The wall column is at x=3; the door replaces (3,4) but
    # in edge-door mode the door is on the FLOOR side.
    # Actually: the door tile is at (4,4) with door_side="west"
    # meaning the wall edge is on the west side of tile (4,4).
    # Wait, looking at real data: door at (36,6) side="west"
    # means the door is at x=36, the wall column is also x=36.
    # Let me place the door correctly.
    #
    # Door replaces the wall tile at x=3, y=4:
    level.tiles[4][3] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="west",
    )

    # Corridor: (2,4) and (1,4) — the player approaches from west
    level.tiles[4][2] = Tile(terrain=Terrain.FLOOR, is_corridor=True)
    level.tiles[4][1] = Tile(terrain=Terrain.FLOOR, is_corridor=True)

    return level


class TestWallRunIsolatedRoom:
    """Room wall with no corridor alongside: walls must be hidden."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_isolated_room_west_door()
        return _fov_with_wall_run_hiding(level, 2, 4)

    def test_player_visible(self, fov):
        assert (2, 4) in fov

    def test_door_visible(self, fov):
        assert (3, 4) in fov

    def test_wall_above_door_hidden(self, fov):
        assert (3, 3) not in fov, (
            "wall (3,3) above door leaks room structure"
        )

    def test_wall_below_door_hidden(self, fov):
        assert (3, 5) not in fov, (
            "wall (3,5) below door leaks room structure"
        )

    def test_far_wall_hidden(self, fov):
        assert (3, 2) not in fov, (
            "wall (3,2) far above door leaks room structure"
        )

    def test_room_interior_not_visible(self, fov):
        assert (4, 4) not in fov, (
            "room interior visible through closed door"
        )


# ── Scenario B: corridor runs along the room wall ───────────
#
# The corridor is adjacent to the wall tiles. The player can
# see the wall as part of their corridor, so those walls
# should remain visible.
#
#      0 1 2 3 4 5 6
#  0   # # # # # # #
#  1   # # . # # # #    corridor: (2,1)
#  2   # . . D . . #    corridor: (1-2,2), door: (3,2), room: (4-5,2)
#  3   # # . # # # #    corridor: (2,3)
#  4   # # # # # # #
#
# Player at (2,2). Wall tiles (3,1) and (3,3) ARE adjacent to
# visible corridor floor tiles (2,1) and (2,3), so the player
# sees them as corridor walls → they should be VISIBLE.


def _build_corridor_along_room_wall() -> Level:
    level = Level.create_empty("test", "Test", depth=1,
                               width=7, height=5)
    for y in range(5):
        for x in range(7):
            level.tiles[y][x] = Tile(terrain=Terrain.WALL)

    # Corridor
    level.tiles[2][1] = Tile(terrain=Terrain.FLOOR, is_corridor=True)
    level.tiles[1][2] = Tile(terrain=Terrain.FLOOR, is_corridor=True)
    level.tiles[2][2] = Tile(terrain=Terrain.FLOOR, is_corridor=True)
    level.tiles[3][2] = Tile(terrain=Terrain.FLOOR, is_corridor=True)

    # Door
    level.tiles[2][3] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_locked",
        door_side="west",
    )

    # Room
    for y in range(1, 4):
        for x in range(4, 6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    return level


class TestWallRunCorridorAlongside:
    """Corridor adjacent to room wall: walls visible to player stay."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_corridor_along_room_wall()
        return _fov_with_wall_run_hiding(level, 2, 2)

    def test_player_visible(self, fov):
        assert (2, 2) in fov

    def test_door_visible(self, fov):
        assert (3, 2) in fov

    def test_wall_above_door_visible(self, fov):
        """(3,1) is adjacent to visible corridor (2,1) → visible."""
        assert (3, 1) in fov

    def test_wall_below_door_visible(self, fov):
        """(3,3) is adjacent to visible corridor (2,3) → visible."""
        assert (3, 3) in fov

    def test_corridor_above_visible(self, fov):
        assert (2, 1) in fov

    def test_corridor_below_visible(self, fov):
        assert (2, 3) in fov

    def test_room_not_visible(self, fov):
        assert (4, 2) not in fov


# ── Scenario C: player next to wall, door further along ─────
#
# The wall row extends far from the door. Walls near the
# player (with visible floor neighbor) stay visible; walls
# far from the player (no visible floor neighbor) are hidden.
#
#      0 1 2 3 4 5 6 7 8 9
#  0   # # # # # # # # # #
#  1   . . . . . . # . . #    room: (7-8, 1-5)
#  2   . . . . . . # . . #
#  3   . . . . . . D . . #    door: (6,3) side="west"
#  4   . . . . . . # . . #
#  5   . . . . . . # . . #
#  6   # # # # # # # # # #
#  7   . . . # . . . . . .    corridor
#  8   . . . # # # . . . .
#
# Player at (5,3). Wall column x=6: tiles (6,1) and (6,2) have
# no visible floor neighbor → hidden. Tiles (6,4) and (6,5)
# also have no visible floor neighbor → hidden.
# But (6,3) IS the door → visible.
# If the player were at (5,2) instead, (6,2) would be adjacent
# to visible (5,2) → visible; but (6,1) still hidden.


def _build_long_wall_run() -> Level:
    level = Level.create_empty("test", "Test", depth=1,
                               width=10, height=9)

    # Outer walls
    for x in range(10):
        level.tiles[0][x] = Tile(terrain=Terrain.WALL)
        level.tiles[6][x] = Tile(terrain=Terrain.WALL)

    # Room wall column at x=6, y=1-5
    for y in range(1, 6):
        level.tiles[y][6] = Tile(terrain=Terrain.WALL)
    # East wall at x=9, y=1-5
    for y in range(1, 6):
        level.tiles[y][9] = Tile(terrain=Terrain.WALL)

    # Room interior: (7-8, 1-5)
    for y in range(1, 6):
        for x in range(7, 9):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    # Door at (6,3) — west edge
    level.tiles[3][6] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="west",
    )

    # Corridor west of door: (5,3), (4,3), (3,3)
    for x in range(3, 6):
        level.tiles[3][x] = Tile(terrain=Terrain.FLOOR,
                                 is_corridor=True)

    return level


class TestWallRunLongWall:
    """Long wall column: only walls near visible floor stay visible."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_long_wall_run()
        return _fov_with_wall_run_hiding(level, 5, 3)

    def test_door_visible(self, fov):
        assert (6, 3) in fov

    def test_wall_far_above_hidden(self, fov):
        assert (6, 1) not in fov, "far wall leaks room structure"

    def test_wall_above_hidden(self, fov):
        assert (6, 2) not in fov, "wall above door leaks room"

    def test_wall_below_hidden(self, fov):
        assert (6, 4) not in fov, "wall below door leaks room"

    def test_wall_far_below_hidden(self, fov):
        assert (6, 5) not in fov, "far wall leaks room structure"

    def test_corridor_visible(self, fov):
        assert (5, 3) in fov
        assert (4, 3) in fov


class TestWallRunPlayerAdjacentToWall:
    """Player next to a wall tile in the run — that wall visible."""

    @pytest.fixture()
    def fov(self) -> set[tuple[int, int]]:
        level = _build_long_wall_run()
        # Player at (5,2): one tile north of corridor center,
        # adjacent to wall (6,2)
        level.tiles[2][5] = Tile(terrain=Terrain.FLOOR,
                                 is_corridor=True)
        return _fov_with_wall_run_hiding(level, 5, 2)

    def test_adjacent_wall_visible(self, fov):
        """(6,2) is adjacent to player at (5,2) → visible."""
        assert (6, 2) in fov

    def test_far_wall_still_hidden(self, fov):
        """(6,1) has no visible floor neighbor → hidden."""
        assert (6, 1) not in fov

    def test_door_visible(self, fov):
        assert (6, 3) in fov


# ── Scenario E: player inside room with two doors on south wall ─
#
# Matches the real bug scenario: player is inside the room
# looking at two closed doors on the bottom wall. Wall tiles
# between and beside the doors are visible (part of the room
# wall). Corridor tiles behind the doors must NOT be visible.
#
#      0 1 2 3 4 5 6 7 8 9 10 11
#  0   . . . . . . . . . .  .  .    VOID
#  1   . . . # # # # # # #  .  .    room north wall
#  2   . . . # . . . . . #  .  .    room interior
#  3   . . . # . . @ . . #  .  .    room interior (player)
#  4   . . . # . . . . . #  .  .    room interior
#  5   . . . # D # D # # #  .  .    south wall + doors
#  6   . . . . . . . . . .  .  .    corridor/VOID behind
#  7   . . . . . . . . . .  .  .
#
# Doors at (4,5) and (6,5) with door_side="north" (room floor
# is to the north at y=4).
# Wall tiles (5,5), (7,5), (8,5) have visible floor above.
# Corridor tiles (4,6), (6,6) must NOT be visible.

def _build_room_with_two_south_doors() -> Level:
    level = Level.create_empty("test", "Test", depth=1,
                               width=12, height=8)

    # Room walls
    for x in range(3, 10):
        level.tiles[1][x] = Tile(terrain=Terrain.WALL)
        level.tiles[5][x] = Tile(terrain=Terrain.WALL)
    for y in range(1, 6):
        level.tiles[y][3] = Tile(terrain=Terrain.WALL)
        level.tiles[y][9] = Tile(terrain=Terrain.WALL)

    # Room interior: (4-8, 2-4)
    for y in range(2, 5):
        for x in range(4, 9):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    # Doors at (4,5) and (6,5) — door_side="north" because
    # room floor is north (y=4).  Corridor is south (y=6).
    level.tiles[5][4] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="north",
    )
    level.tiles[5][6] = Tile(
        terrain=Terrain.FLOOR,
        feature="door_closed",
        door_side="north",
    )

    # Corridors behind doors
    level.tiles[6][4] = Tile(terrain=Terrain.FLOOR,
                             is_corridor=True)
    level.tiles[6][6] = Tile(terrain=Terrain.FLOOR,
                             is_corridor=True)

    return level


# ── Hatch-clear computation ─────────────────────────────────
#
# compute_hatch_clear returns the set of explored tiles that
# should have their hatch removed on the client. Only FLOOR
# and WATER tiles are included (WALL/VOID stay hatched to
# prevent SVG bleed). Closed doors with an unexplored corridor
# side are excluded so their expand doesn't leak.


class TestHatchClearBasic:
    """Only FLOOR/WATER explored tiles appear in hatch_clear."""

    @pytest.fixture()
    def level(self) -> Level:
        level = _build_room_with_two_south_doors()
        # Mark the room interior + walls as explored
        for y in range(1, 6):
            for x in range(3, 10):
                tile = level.tile_at(x, y)
                if tile:
                    tile.explored = True
        return level

    def test_floor_tiles_included(self, level):
        hc = compute_hatch_clear(level)
        # Room floor tiles should be in hatch_clear
        for x in range(4, 9):
            for y in range(2, 5):
                assert (x, y) in hc, (
                    f"explored floor ({x},{y}) should be in "
                    f"hatch_clear"
                )

    def test_wall_tiles_excluded(self, level):
        hc = compute_hatch_clear(level)
        # Wall tiles should NOT be in hatch_clear
        for x in range(3, 10):
            tile = level.tile_at(x, 1)
            if tile and tile.terrain == Terrain.WALL:
                assert (x, 1) not in hc, (
                    f"wall ({x},1) should not be in hatch_clear"
                )

    def test_void_tiles_excluded(self, level):
        hc = compute_hatch_clear(level)
        # VOID tiles (even if somehow explored) excluded
        level.tile_at(0, 0).explored = True
        hc = compute_hatch_clear(level)
        assert (0, 0) not in hc

    def test_unexplored_tiles_excluded(self, level):
        hc = compute_hatch_clear(level)
        # Corridor behind door is unexplored
        assert (4, 6) not in hc
        assert (6, 6) not in hc


class TestHatchClearDoorBlocking:
    """Closed doors with unexplored corridor side are excluded."""

    @pytest.fixture()
    def level(self) -> Level:
        level = _build_room_with_two_south_doors()
        # Explore room interior + wall row + doors
        for y in range(1, 6):
            for x in range(3, 10):
                tile = level.tile_at(x, y)
                if tile:
                    tile.explored = True
        return level

    def test_closed_door_corridor_unexplored(self, level):
        """Door tile excluded when corridor side not explored."""
        hc = compute_hatch_clear(level)
        # (4,5) has door_side="north", corridor at (4,6)
        # (4,6) is unexplored → door excluded
        assert (4, 5) not in hc
        assert (6, 5) not in hc

    def test_closed_door_corridor_explored(self, level):
        """Door tile included when corridor side is explored."""
        # Explore the corridor behind door (4,5)
        level.tile_at(4, 6).explored = True
        hc = compute_hatch_clear(level)
        assert (4, 5) in hc
        # Other door still blocked
        assert (6, 5) not in hc

    def test_open_door_always_included(self, level):
        """Open doors are always in hatch_clear."""
        level.tile_at(4, 5).feature = "door_open"
        hc = compute_hatch_clear(level)
        assert (4, 5) in hc


# ── Hatch-clear for non-rect room shapes ───────────────────
#
# Octagonal, circular, and cross rooms have diagonal or curved
# walls drawn as SVG polygons. The corner tiles where diagonals
# sit are WALL terrain. compute_hatch_clear must include these
# so the hatch doesn't cover the visible diagonal walls.
#
#      0 1 2 3 4 5 6 7 8
#  0   . . . . . . . . .    VOID
#  1   . . . # # # . . .    top wall (clipped corners)
#  2   . . # . . . # . .    octagon interior
#  3   . . # . @ . # . .    octagon interior (player)
#  4   . . # . . . # . .    octagon interior
#  5   . . . # # # . . .    bottom wall (clipped corners)
#  6   . . . . . . . . .    VOID
#
# Room rect (2,1, 5,5). OctagonShape clips corners:
# (2,1), (6,1), (2,5), (6,5) are WALL (clipped corners).
# These tiles have the octagonal outline drawn on them and
# should be in hatch_clear when explored.


def _build_octagonal_room() -> Level:
    level = Level.create_empty("test", "Test", depth=1,
                               width=9, height=7)
    r = Rect(2, 1, 5, 5)
    shape = OctagonShape()
    room = Room(id="room_0", rect=r, shape=shape)
    level.rooms.append(room)

    floor = shape.floor_tiles(r)
    for y in range(r.y, r.y2):
        for x in range(r.x, r.x2):
            if (x, y) in floor:
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
            else:
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)

    return level


class TestHatchClearOctagonCorners:
    """Octagon corner WALL tiles included in hatch_clear."""

    @pytest.fixture()
    def level(self) -> Level:
        level = _build_octagonal_room()
        r = level.rooms[0].rect
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                tile = level.tile_at(x, y)
                if tile:
                    tile.explored = True
        return level

    def test_floor_tiles_included(self, level):
        hc = compute_hatch_clear(level)
        assert (4, 3) in hc  # center floor

    def test_corner_wall_tiles_included(self, level):
        """WALL tiles at octagon corners should be in hatch_clear
        so the diagonal walls are not covered by hatching."""
        hc = compute_hatch_clear(level)
        r = level.rooms[0].rect
        floor = level.rooms[0].floor_tiles()
        # Find WALL tiles inside the room bounding rect
        corner_walls = [
            (x, y)
            for y in range(r.y, r.y2)
            for x in range(r.x, r.x2)
            if (x, y) not in floor
        ]
        assert len(corner_walls) > 0, "no corner walls found"
        for pos in corner_walls:
            assert pos in hc, (
                f"octagon corner wall {pos} should be in "
                f"hatch_clear"
            )

    def test_border_wall_tiles_included(self, level):
        """WALL tiles 1 tile outside the room rect should be
        included — the SVG outline can extend beyond the rect."""
        r = level.rooms[0].rect
        # Mark border tiles as explored
        for x in range(r.x - 1, r.x2 + 1):
            for y in [r.y - 1, r.y2]:
                tile = level.tile_at(x, y)
                if tile:
                    tile.explored = True
        hc = compute_hatch_clear(level)
        # At least some border WALL tiles should be included
        border_walls = [
            (x, y)
            for x in range(r.x - 1, r.x2 + 1)
            for y in [r.y - 1, r.y2]
            if level.tile_at(x, y)
            and level.tile_at(x, y).terrain == Terrain.WALL
            and level.tile_at(x, y).explored
        ]
        for pos in border_walls:
            assert pos in hc, (
                f"border wall {pos} should be in hatch_clear"
            )

    def test_wall_far_from_room_excluded(self, level):
        """WALL tiles far from any room rect stay excluded."""
        # Mark a wall tile far from the room as explored
        level.tiles[0][0] = Tile(terrain=Terrain.WALL)
        level.tile_at(0, 0).explored = True
        hc = compute_hatch_clear(level)
        assert (0, 0) not in hc


class TestPlayerInsideRoomTwoSouthDoors:
    """Player inside room: corridor behind closed doors not visible.

    This tests the real scenario where the player is inside a room
    and can see the room wall with closed doors. Wall tiles between
    the doors have visible floor neighbors (room floor above), so
    they are correctly visible. But corridor tiles behind doors and
    VOID tiles flanking corridors must NOT be visible.
    """

    @pytest.fixture()
    def level(self) -> Level:
        return _build_room_with_two_south_doors()

    @pytest.fixture()
    def fov(self, level) -> set[tuple[int, int]]:
        return _fov_with_wall_run_hiding(level, 6, 3)

    def test_player_visible(self, fov):
        assert (6, 3) in fov

    def test_room_floor_visible(self, fov):
        for x in range(4, 9):
            for y in range(2, 5):
                assert (x, y) in fov, (
                    f"room floor ({x},{y}) should be visible"
                )

    def test_door_tiles_visible(self, fov):
        """Closed doors are visible (player sees the door)."""
        assert (4, 5) in fov
        assert (6, 5) in fov

    def test_wall_between_doors_visible(self, fov):
        """Wall at (5,5) between the two doors — has visible
        floor neighbor (5,4) above — should be visible."""
        assert (5, 5) in fov

    def test_wall_beside_doors_visible(self, fov):
        """Walls at (7,5), (8,5) beside doors — have visible
        floor neighbors above — should be visible."""
        assert (7, 5) in fov
        assert (8, 5) in fov

    def test_corridor_behind_door_not_visible(self, fov):
        """Corridor tiles behind closed doors must NOT be visible.
        The door blocks sight."""
        assert (4, 6) not in fov, (
            "corridor (4,6) visible through closed door"
        )
        assert (6, 6) not in fov, (
            "corridor (6,6) visible through closed door"
        )

    def test_void_flanking_corridor_not_visible(self, fov):
        """VOID tiles next to corridor must not be visible."""
        assert (3, 6) not in fov
        assert (5, 6) not in fov
        assert (7, 6) not in fov

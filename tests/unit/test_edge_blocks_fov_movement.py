"""FOV + movement consult edge walls (M3).

The ``interior_edges`` set gains two engine-side helpers. Both
consult ``Level.interior_edges`` canonically and apply door
suppression: an edge is passable when the tile on either side has
a matching ``door_open`` feature with ``door_side`` pointing at
that edge. Closed / locked doors keep blocking via the tile-
feature path and are NOT treated as open for edge purposes.
"""

from __future__ import annotations

import pytest

from nhc.dungeon.edges import (
    edge_blocks_movement, edge_blocks_sight,
    edge_has_open_door, edge_shadow_tiles,
)
from nhc.dungeon.model import Level, Terrain, Tile


def _floor_level(width: int = 6, height: int = 6) -> Level:
    level = Level.create_empty("t", "t", 1, width, height)
    for y in range(height):
        for x in range(width):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    return level


class TestEdgeBlocksSight:
    def test_walled_edge_blocks(self) -> None:
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))  # edge between (3,2) & (3,3)
        assert edge_blocks_sight(level, (3, 2), (3, 3))
        assert edge_blocks_sight(level, (3, 3), (3, 2))

    def test_no_edge_does_not_block(self) -> None:
        level = _floor_level()
        assert not edge_blocks_sight(level, (3, 2), (3, 3))

    def test_open_door_suppresses_edge(self) -> None:
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))
        # Door on the tile south of the edge, door_side pointing
        # north at the edge.
        level.tiles[3][3].feature = "door_open"
        level.tiles[3][3].door_side = "north"
        assert not edge_blocks_sight(level, (3, 2), (3, 3))
        assert not edge_blocks_sight(level, (3, 3), (3, 2))

    def test_closed_door_still_blocks_edge(self) -> None:
        """Closed doors keep blocking via the tile feature. The
        edge-sight helper treats them as NOT suppressing the
        edge — callers that mix tile + edge blocking remain
        correct either way."""
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))
        level.tiles[3][3].feature = "door_closed"
        level.tiles[3][3].door_side = "north"
        assert edge_blocks_sight(level, (3, 2), (3, 3))

    def test_door_on_other_side_of_edge(self) -> None:
        """Door on the tile NORTH of the edge, door_side pointing
        south at the edge — same suppression semantics."""
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))
        level.tiles[2][3].feature = "door_open"
        level.tiles[2][3].door_side = "south"
        assert not edge_blocks_sight(level, (3, 2), (3, 3))


class TestEdgeBlocksMovement:
    def test_walled_edge_blocks_orthogonal_step(self) -> None:
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))
        assert edge_blocks_movement(level, (3, 2), (3, 3))

    def test_open_door_suppresses_movement(self) -> None:
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))
        level.tiles[3][3].feature = "door_open"
        level.tiles[3][3].door_side = "north"
        assert not edge_blocks_movement(level, (3, 2), (3, 3))

    def test_diagonal_blocked_when_either_leg_walled(self) -> None:
        """Stepping diagonally from (3, 2) to (4, 3) is blocked if
        the south edge of (3, 2) is walled OR the east edge of
        (3, 2) is walled. Prevents corner-squeezing through an
        edge wall."""
        level = _floor_level()
        level.interior_edges.add((3, 3, "north"))  # south of (3, 2)
        assert edge_blocks_movement(level, (3, 2), (4, 3))

        level2 = _floor_level()
        level2.interior_edges.add((4, 2, "west"))  # east of (3, 2)
        assert edge_blocks_movement(level2, (3, 2), (4, 3))

    def test_diagonal_clear_passes(self) -> None:
        level = _floor_level()
        assert not edge_blocks_movement(level, (3, 2), (4, 3))


class TestEdgeShadowTiles:
    """Regression: FOV must not leak past a partial interior wall.

    The BFS in :func:`edge_shadow_tiles` respects interior edges
    but used to ignore :attr:`Tile.blocks_sight`. On a real
    building floor, the interior edge wall runs only across the
    room-to-room boundary -- the perimeter wall columns on either
    side of the rooms are ordinary WALL tiles with no edge entry.
    The BFS wrapped around the interior edge by walking through
    those perimeter wall tiles, ending up in the adjacent room,
    so nothing marked the adjacent-room floors as shadowed and
    the tile-based shadowcaster reported them visible. Observed
    live on ``site_18_4_b0_f0`` with the player in room 1 seeing
    clearly into room 0 through a closed interior door.
    """

    @staticmethod
    def _two_chamber_level() -> Level:
        """7x7 level: perimeter wall ring around a 5x5 floor area,
        split horizontally by a partial interior edge wall at
        ``y=3 'north'`` for ``x=1..5``. Mirrors the production
        shape that triggered the FOV leak."""
        level = Level.create_empty("t", "t", 1, 7, 7)
        for y in range(7):
            for x in range(7):
                if x in (0, 6) or y in (0, 6):
                    level.tiles[y][x] = Tile(terrain=Terrain.WALL)
                else:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        for x in range(1, 6):
            level.interior_edges.add((x, 3, "north"))
        return level

    def test_bfs_does_not_wrap_around_partial_wall(self) -> None:
        # Radius 8 matches the production FOV radius that
        # exposed the bug; small radii mask it by terminating
        # BFS before it can wrap all the way around.
        level = self._two_chamber_level()
        shadow = edge_shadow_tiles(level, (3, 4), radius=8)
        # Every floor tile in the north chamber (y=1, 2) must be
        # shadowed -- no sight path from the south-chamber origin
        # crosses to the north chamber without going through
        # either the interior edge wall or the perimeter walls.
        for y in (1, 2):
            for x in range(1, 6):
                assert (x, y) in shadow, (
                    f"({x},{y}) leaked past interior edge wall "
                    f"(BFS wrapped around via perimeter walls)"
                )

    def test_south_chamber_floors_stay_visible(self) -> None:
        """Sanity: the fix must not over-shadow the player's own
        chamber."""
        level = self._two_chamber_level()
        shadow = edge_shadow_tiles(level, (3, 4), radius=8)
        for y in (3, 4, 5):
            for x in range(1, 6):
                assert (x, y) not in shadow, (
                    f"({x},{y}) wrongly shadowed in the same "
                    f"chamber as the origin"
                )

    def test_origin_reachable_even_on_sight_blocker(self) -> None:
        """Origin is exempt from the 'don't expand from sight-
        blockers' guard -- a player standing on a closed door
        must still see their own tile, and BFS must still reach
        adjacent passable tiles."""
        level = self._two_chamber_level()
        level.tiles[4][3].feature = "door_closed"
        shadow = edge_shadow_tiles(level, (3, 4), radius=8)
        assert (3, 4) not in shadow
        for x in range(1, 6):
            assert (x, 4) not in shadow


class TestEdgeHasOpenDoor:
    def test_no_door_returns_false(self) -> None:
        level = _floor_level()
        assert not edge_has_open_door(level, 3, 3, "north")

    def test_open_door_south_side(self) -> None:
        level = _floor_level()
        # Canonical edge (3, 3, "north"). Door on (3, 3) opens north.
        level.tiles[3][3].feature = "door_open"
        level.tiles[3][3].door_side = "north"
        assert edge_has_open_door(level, 3, 3, "north")

    def test_open_door_north_side(self) -> None:
        level = _floor_level()
        # Door on (3, 2) with door_side = south — same edge.
        level.tiles[2][3].feature = "door_open"
        level.tiles[2][3].door_side = "south"
        assert edge_has_open_door(level, 3, 3, "north")

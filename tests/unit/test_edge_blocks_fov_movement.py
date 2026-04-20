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
    edge_has_open_door,
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

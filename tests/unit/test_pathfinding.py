"""Tests for A* pathfinding."""

from nhc.ai.pathfinding import astar


class TestAstar:
    def test_straight_line(self):
        path = astar((0, 0), (5, 0), lambda x, y: True)
        assert len(path) == 5
        assert path[-1] == (5, 0)

    def test_around_wall(self):
        # Wall from (2, 0) to (2, 3)
        walls = {(2, y) for y in range(4)}

        def walkable(x, y):
            return (x, y) not in walls

        path = astar((0, 0), (4, 0), walkable)
        assert path  # Path should exist
        assert path[-1] == (4, 0)
        # No path point should be on a wall
        for p in path:
            assert p not in walls

    def test_no_path(self):
        # Completely blocked
        def walkable(x, y):
            return x < 3

        path = astar((0, 0), (5, 0), walkable)
        assert path == []

    def test_same_start_goal(self):
        path = astar((3, 3), (3, 3), lambda x, y: True)
        assert path == []

    def test_adjacent(self):
        path = astar((0, 0), (1, 1), lambda x, y: True)
        assert path == [(1, 1)]

    def test_diagonal_path(self):
        path = astar((0, 0), (3, 3), lambda x, y: True)
        # Diagonal should be 3 steps
        assert len(path) == 3
        assert path[-1] == (3, 3)

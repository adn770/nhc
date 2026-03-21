"""A* pathfinding on dungeon grid."""

from __future__ import annotations

import heapq
from typing import Callable

from nhc.utils.spatial import chebyshev, neighbors


def astar(
    start: tuple[int, int],
    goal: tuple[int, int],
    is_walkable: Callable[[int, int], bool],
    max_steps: int = 200,
) -> list[tuple[int, int]]:
    """A* pathfinding with 8-directional movement.

    Returns path as list of (x, y) from start to goal (exclusive of start),
    or empty list if no path found within max_steps.
    """
    if start == goal:
        return []

    open_set: list[tuple[int, tuple[int, int]]] = []
    heapq.heappush(open_set, (0, start))

    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    g_score: dict[tuple[int, int], int] = {start: 0}
    steps = 0

    while open_set and steps < max_steps:
        steps += 1
        _, current = heapq.heappop(open_set)

        if current == goal:
            # Reconstruct path
            path: list[tuple[int, int]] = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.reverse()
            return path

        for nx, ny in neighbors(*current):
            if not is_walkable(nx, ny):
                continue

            # Diagonal moves cost same as cardinal (Chebyshev)
            tentative_g = g_score[current] + 1
            neighbor = (nx, ny)

            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + chebyshev(nx, ny, *goal)
                heapq.heappush(open_set, (f, neighbor))

    return []

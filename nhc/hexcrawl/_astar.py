"""A* pathfinding and MST for the hex grid.

Provides :func:`hex_astar` for shortest-path routing over
biome-weighted hex cells, and :func:`settlement_mst` for
minimum spanning tree over settlement coordinates.
"""

from __future__ import annotations

import heapq

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import Biome, HexCell


def hex_astar(
    start: HexCoord,
    goal: HexCoord,
    cells: dict[HexCoord, HexCell],
    biome_costs: dict[Biome, int],
    max_steps: int = 2000,
) -> list[HexCoord]:
    """Find the cheapest path from *start* to *goal*."""
    if start == goal:
        return [start]
    if start not in cells or goal not in cells:
        return []
    counter = 0
    open_set: list[tuple[float, int, HexCoord]] = [
        (0.0, counter, start),
    ]
    came_from: dict[HexCoord, HexCoord] = {}
    g_score: dict[HexCoord, float] = {start: 0.0}
    expanded = 0
    while open_set and expanded < max_steps:
        _, _, current = heapq.heappop(open_set)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        expanded += 1
        cur_g = g_score.get(current, float("inf"))
        for nbr in neighbors(current):
            if nbr not in cells:
                continue
            cost = biome_costs.get(cells[nbr].biome, 2)
            if cost >= 50:
                continue
            if any(s.type == "path" for s in cells[nbr].edges):
                cost = max(1, cost - 1)
            tentative_g = cur_g + cost
            if tentative_g < g_score.get(nbr, float("inf")):
                came_from[nbr] = current
                g_score[nbr] = tentative_g
                f = tentative_g + distance(nbr, goal)
                counter += 1
                heapq.heappush(open_set, (f, counter, nbr))
    return []


def settlement_mst(
    settlements: list[HexCoord],
) -> list[tuple[HexCoord, HexCoord]]:
    """Prim's MST over *settlements* using hex distance."""
    if len(settlements) < 2:
        return []
    in_tree: set[HexCoord] = {settlements[0]}
    edges: list[tuple[HexCoord, HexCoord]] = []
    while len(in_tree) < len(settlements):
        best: tuple[int, HexCoord, HexCoord] | None = None
        for s in in_tree:
            for t in settlements:
                if t in in_tree:
                    continue
                d = distance(s, t)
                if best is None or d < best[0]:
                    best = (d, s, t)
        if best is None:
            break
        _, a, b = best
        in_tree.add(b)
        edges.append((a, b))
    return edges

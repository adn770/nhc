"""Path generation for the hexcrawl overland map.

Paths connect settlements (cities, villages) and optionally
towers, keeps, and caves via A* shortest paths over the hex
grid. Each hex along a path carries an
:class:`~nhc.hexcrawl.model.EdgeSegment` with entry/exit edge
indices so the frontend can draw the path as a continuous line
crossing hex edges.

The algorithm:

1. Build a minimum spanning tree (MST) over all settlement
   hexes so every community is reachable.
2. A* each MST edge to get the actual terrain route.
3. Optionally connect towers/keeps and caves to the nearest
   settlement with configurable probability.
4. Stamp ``EdgeSegment(type="path", ...)`` on each hex along
   each route.
"""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl._rivers import direction_index


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PathParams:
    """Pack-configurable knobs for path generation."""

    connect_towers: float = 0.6
    connect_caves: float = 0.2


# ---------------------------------------------------------------------------
# A* on the hex grid
# ---------------------------------------------------------------------------


def hex_astar(
    start: HexCoord,
    goal: HexCoord,
    cells: dict[HexCoord, HexCell],
    biome_costs: dict[Biome, int],
    max_steps: int = 2000,
) -> list[HexCoord]:
    """Find the cheapest path from *start* to *goal* on the hex grid.

    Uses biome travel costs as edge weights and hex distance as the
    heuristic. Returns an empty list if no path exists within
    *max_steps* expansions.
    """
    if start == goal:
        return [start]
    if start not in cells or goal not in cells:
        return []

    # Priority queue: (f_cost, counter, coord).
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
            # Reconstruct path.
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
            # WATER is effectively impassable.
            if cost >= 50:
                continue
            # Slightly cheaper to join an existing path (encourages
            # path merging at crossroads).
            if any(s.type == "path" for s in cells[nbr].edges):
                cost = max(1, cost - 1)
            tentative_g = cur_g + cost
            if tentative_g < g_score.get(nbr, float("inf")):
                came_from[nbr] = current
                g_score[nbr] = tentative_g
                f = tentative_g + distance(nbr, goal)
                counter += 1
                heapq.heappush(open_set, (f, counter, nbr))

    return []  # no path found


# ---------------------------------------------------------------------------
# MST over settlements
# ---------------------------------------------------------------------------


def _settlement_mst(
    settlements: list[HexCoord],
) -> list[tuple[HexCoord, HexCoord]]:
    """Prim's MST over *settlements* using hex distance as weight.

    Returns a list of (a, b) edges connecting every settlement
    with minimum total distance.
    """
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


# ---------------------------------------------------------------------------
# Edge stamping
# ---------------------------------------------------------------------------


def _stamp_path_edges(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
) -> None:
    """Add ``EdgeSegment(type="path", ...)`` to each cell along *path*."""
    for i, coord in enumerate(path):
        if i == 0:
            entry: int | None = None
        else:
            d = direction_index(path[i - 1], coord)
            entry = (d + 3) % 6

        if i == len(path) - 1:
            exit_: int | None = None
        else:
            exit_ = direction_index(coord, path[i + 1])

        cells[coord].edges.append(
            EdgeSegment(type="path", entry_edge=entry, exit_edge=exit_),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_SETTLEMENT_FEATURES = frozenset({
    HexFeatureType.CITY,
    HexFeatureType.VILLAGE,
})

_TOWER_FEATURES = frozenset({
    HexFeatureType.TOWER,
    HexFeatureType.KEEP,
})


def generate_paths(
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    params: PathParams,
    biome_costs: dict[Biome, int],
) -> list[list[HexCoord]]:
    """Generate paths on the overland map.

    Mutates *cells* in place, stamping ``EdgeSegment`` on each hex
    a path crosses. Returns the list of path coord sequences for
    storage on :attr:`HexWorld.paths`.
    """
    # 1. Collect settlements.
    settlements = [
        c for c, cell in cells.items()
        if cell.feature in _SETTLEMENT_FEATURES
    ]

    paths: list[list[HexCoord]] = []

    # 2. MST over settlements → A* each edge.
    mst_edges = _settlement_mst(settlements)
    for a, b in mst_edges:
        route = hex_astar(a, b, cells, biome_costs)
        if route and len(route) >= 2:
            _stamp_path_edges(route, cells)
            paths.append(route)

    # 3. Optionally connect towers/keeps to nearest settlement.
    if settlements and params.connect_towers > 0:
        towers = [
            c for c, cell in cells.items()
            if cell.feature in _TOWER_FEATURES
        ]
        for tower in towers:
            if rng.random() >= params.connect_towers:
                continue
            nearest = min(settlements, key=lambda s: distance(s, tower))
            route = hex_astar(tower, nearest, cells, biome_costs)
            if route and len(route) >= 2:
                _stamp_path_edges(route, cells)
                paths.append(route)

    # 4. Optionally connect caves to nearest settlement.
    if settlements and params.connect_caves > 0:
        caves = [
            c for c, cell in cells.items()
            if cell.feature is HexFeatureType.CAVE
        ]
        for cave in caves:
            if rng.random() >= params.connect_caves:
                continue
            nearest = min(settlements, key=lambda s: distance(s, cave))
            route = hex_astar(cave, nearest, cells, biome_costs)
            if route and len(route) >= 2:
                _stamp_path_edges(route, cells)
                paths.append(route)

    return paths

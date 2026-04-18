"""Enhanced road generation for the continental generator.

Extends the v1 path algorithm with:
- Modified cost weights (sandlands/deadlands heavily penalised)
- Dead-end detection with tower/keep placement
- Cave connections to nearest road (not nearest settlement)
"""

from __future__ import annotations

import random

import heapq

from nhc.hexcrawl.coords import (
    HexCoord, direction_index, distance, neighbors,
)
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import PathParams


# ---------------------------------------------------------------------------
# A* on the hex grid (moved from _paths.py)
# ---------------------------------------------------------------------------


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


def _settlement_mst(
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


# Terrain costs for road routing. Sandlands and deadlands are
# heavily penalised but not impassable (roads will detour if
# possible but can cross if no alternative exists).
_ROAD_COSTS: dict[Biome, int] = {
    Biome.GREENLANDS: 1,
    Biome.HILLS: 2,
    Biome.DRYLANDS: 3,
    Biome.MARSH: 3,
    Biome.SWAMP: 4,
    Biome.ICELANDS: 5,
    Biome.FOREST: 6,
    Biome.MOUNTAIN: 8,
    Biome.SANDLANDS: 15,
    Biome.DEADLANDS: 15,
    Biome.WATER: 99,
}

_SETTLEMENT_FEATURES = frozenset({
    HexFeatureType.CITY,
    HexFeatureType.VILLAGE,
})

_TOWER_FEATURES = frozenset({
    HexFeatureType.TOWER,
    HexFeatureType.KEEP,
})


# ---------------------------------------------------------------------------
# Edge stamping
# ---------------------------------------------------------------------------


def _stamp_path_edges(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
) -> None:
    """Add ``EdgeSegment(type="path", ...)`` to each cell.

    Skips hexes that already carry a path segment covering the
    same edge pair (or its reverse), preventing duplicate stamps
    when two paths share the same stretch of road.
    """
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

        # Check for duplicate or reverse segment already present.
        existing = cells[coord].edges
        duplicate = False
        for seg in existing:
            if seg.type != "path":
                continue
            if (seg.entry_edge == entry and seg.exit_edge == exit_):
                duplicate = True
                break
            # Reverse: same road traversed in opposite direction.
            if (seg.entry_edge == exit_ and seg.exit_edge == entry):
                duplicate = True
                break
        if not duplicate:
            cells[coord].edges.append(
                EdgeSegment(
                    type="path", entry_edge=entry, exit_edge=exit_,
                ),
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_paths(
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    params: PathParams,
) -> list[list[HexCoord]]:
    """Generate roads on the overland map (continental algorithm).

    Mutates *cells* in place, stamping ``EdgeSegment`` on each
    hex a road crosses. Returns the list of path coord sequences.
    """
    # 1. Collect settlements.
    settlements = [
        c for c, cell in cells.items()
        if cell.feature in _SETTLEMENT_FEATURES
    ]

    paths: list[list[HexCoord]] = []

    # 2. MST over settlements -> A* each edge.
    mst_edges = _settlement_mst(settlements)
    for a, b in mst_edges:
        route = hex_astar(a, b, cells, _ROAD_COSTS)
        if route and len(route) >= 2:
            _stamp_path_edges(route, cells)
            paths.append(route)

    # 3. Connect caves to nearest road hex (not nearest settlement).
    if params.connect_caves > 0:
        road_hexes = {
            h for path in paths for h in path
        }
        caves = [
            c for c, cell in cells.items()
            if cell.feature is HexFeatureType.CAVE
        ]
        for cave in caves:
            if rng.random() >= params.connect_caves:
                continue
            if not road_hexes:
                # Fallback: connect to nearest settlement
                if settlements:
                    nearest = min(
                        settlements,
                        key=lambda s: distance(s, cave),
                    )
                    route = hex_astar(
                        cave, nearest, cells, _ROAD_COSTS,
                    )
                    if route and len(route) >= 2:
                        _stamp_path_edges(route, cells)
                        paths.append(route)
                        road_hexes.update(route)
                continue
            # Find nearest hex on any existing road.
            nearest_road = min(
                road_hexes,
                key=lambda h: distance(h, cave),
            )
            route = hex_astar(
                cave, nearest_road, cells, _ROAD_COSTS,
            )
            if route and len(route) >= 2:
                _stamp_path_edges(route, cells)
                paths.append(route)
                road_hexes.update(route)

    # 4. Optionally connect towers/keeps to nearest settlement.
    if settlements and params.connect_towers > 0:
        towers = [
            c for c, cell in cells.items()
            if cell.feature in _TOWER_FEATURES
        ]
        for tower in towers:
            if rng.random() >= params.connect_towers:
                continue
            nearest = min(
                settlements,
                key=lambda s: distance(s, tower),
            )
            route = hex_astar(
                tower, nearest, cells, _ROAD_COSTS,
            )
            if route and len(route) >= 2:
                _stamp_path_edges(route, cells)
                paths.append(route)

    # 5. Dead-end detection: road endpoints that are not
    # settlements get a TOWER or KEEP.
    for path in paths:
        for endpoint in (path[0], path[-1]):
            cell = cells[endpoint]
            if (
                cell.feature not in _SETTLEMENT_FEATURES
                and cell.feature not in _TOWER_FEATURES
                and cell.feature is HexFeatureType.NONE
            ):
                cell.feature = rng.choice([
                    HexFeatureType.TOWER,
                    HexFeatureType.KEEP,
                ])

    return paths



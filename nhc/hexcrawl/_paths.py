"""Road generation for the hexcrawl overland map.

Connects settlements via terrain-aware A* routing, handles
dead-end tower/keep placement, and connects caves to the
nearest road.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import HexCell, HexFeatureType
from nhc.hexcrawl.pack import PathParams
from nhc.hexcrawl._astar import hex_astar, settlement_mst
from nhc.hexcrawl._biome_data import (
    ROAD_COSTS,
    SETTLEMENT_FEATURES,
    TOWER_FEATURES,
)


# ---------------------------------------------------------------------------
# Edge stamping
# ---------------------------------------------------------------------------


def _stamp_path_edges(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
) -> None:
    """Add ``EdgeSegment(type="path", ...)`` to each cell."""
    from nhc.hexcrawl._edge_stamping import stamp_edge_path
    stamp_edge_path(path, cells, "path", check_duplicates=True)


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
        if cell.feature in SETTLEMENT_FEATURES
    ]

    paths: list[list[HexCoord]] = []

    # 2. MST over settlements -> A* each edge.
    mst_edges = settlement_mst(settlements)
    for a, b in mst_edges:
        route = hex_astar(a, b, cells, ROAD_COSTS)
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
                        cave, nearest, cells, ROAD_COSTS,
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
                cave, nearest_road, cells, ROAD_COSTS,
            )
            if route and len(route) >= 2:
                _stamp_path_edges(route, cells)
                paths.append(route)
                road_hexes.update(route)

    # 4. Optionally connect towers/keeps to nearest settlement.
    if settlements and params.connect_towers > 0:
        towers = [
            c for c, cell in cells.items()
            if cell.feature in TOWER_FEATURES
        ]
        for tower in towers:
            if rng.random() >= params.connect_towers:
                continue
            nearest = min(
                settlements,
                key=lambda s: distance(s, tower),
            )
            route = hex_astar(
                tower, nearest, cells, ROAD_COSTS,
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
                cell.feature not in SETTLEMENT_FEATURES
                and cell.feature not in TOWER_FEATURES
                and cell.feature is HexFeatureType.NONE
            ):
                cell.feature = rng.choice([
                    HexFeatureType.TOWER,
                    HexFeatureType.KEEP,
                ])

    return paths



"""Enhanced road generation for the continental_v2 generator.

Extends the v1 path algorithm with:
- Modified cost weights (sandlands/deadlands heavily penalised)
- Dead-end detection with tower/keep placement
- Cave connections to nearest road (not nearest settlement)
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import PathParams
from nhc.hexcrawl._paths import hex_astar, _settlement_mst
from nhc.hexcrawl._rivers import direction_index


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


def generate_paths_v2(
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    params: PathParams,
) -> list[list[HexCoord]]:
    """Generate roads on the overland map (v2 algorithm).

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

    # 5. Merge junction edges: where multiple roads share a hex,
    # replace overlapping segments with a star topology so all
    # arms meet at the hex center.
    _merge_junction_edges(cells)

    # 6. Dead-end detection: road endpoints that are not
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


def _merge_junction_edges(
    cells: dict[HexCoord, HexCell],
) -> None:
    """Convert true junction hexes into star topology.

    A true junction is a hex where 3+ distinct edge indices
    meet (roads branching, not just a single road passing
    through). Replace its path segments with one arm per edge,
    each running from the edge to the hex center. Hexes with
    only 2 edges (a road passing through) are left as-is.
    """
    for coord, cell in cells.items():
        path_segs = [s for s in cell.edges if s.type == "path"]
        if len(path_segs) < 2:
            continue

        # Collect all unique edge indices from all path segments.
        edge_indices: set[int] = set()
        for seg in path_segs:
            if seg.entry_edge is not None:
                edge_indices.add(seg.entry_edge)
            if seg.exit_edge is not None:
                edge_indices.add(seg.exit_edge)

        # Only merge true junctions (3+ distinct edges).
        # A through-route has exactly 2 edges and should stay
        # as a single entry->exit segment.
        if len(edge_indices) < 3:
            continue

        # Remove old path segments.
        cell.edges = [s for s in cell.edges if s.type != "path"]

        # Add one arm per edge: from edge to center.
        for edge_idx in sorted(edge_indices):
            cell.edges.append(
                EdgeSegment(
                    type="path",
                    entry_edge=edge_idx,
                    exit_edge=None,
                ),
            )

"""Enhanced river generation for the continental_v2 generator.

Extends the v1 river algorithm with:
- Forest crossing (allowed, not blocked)
- Drylands/sandlands termination (river dries up)
- Lake creation at low-elevation convergence points
- Drainage-basin-aware source selection
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, distance, neighbors
from nhc.hexcrawl.model import Biome, EdgeSegment, HexCell, HexFeatureType
from nhc.hexcrawl.pack import ContinentalParams, RiverParams
from nhc.hexcrawl._rivers import direction_index


# Biomes where rivers die (terminate, not route around).
_TERMINAL_BIOMES: frozenset[Biome] = frozenset({
    Biome.DRYLANDS, Biome.SANDLANDS,
})

# Lake-eligible biomes.
_LAKE_BIOMES: frozenset[Biome] = frozenset({
    Biome.GREENLANDS, Biome.MARSH,
})

# Maximum elevation for lake creation.
_LAKE_ELEVATION_MAX = 0.15


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def _trace_river_v2(
    source: HexCoord,
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    visited: set[HexCoord],
    params: RiverParams,
    continental: ContinentalParams,
) -> list[HexCoord]:
    """Walk downhill from *source*, collecting the river path.

    Key differences from v1:
    - Forest is not avoided; rivers can cross forest hexes.
    - Entering drylands or sandlands terminates the river.
    - Low-elevation greenlands/marsh may become lakes.
    """
    path: list[HexCoord] = [source]
    visited.add(source)
    current = source

    while True:
        # Check terminal biome: river dries up here.
        if cells[current].biome in _TERMINAL_BIOMES and current != source:
            break

        # Check water termination (river reached the sea).
        if cells[current].biome is Biome.WATER and current != source:
            break

        # Check lake creation — only after the river has some
        # length so short rivers don't all end in lakes.
        if (
            len(path) >= 6
            and current != source
            and cells[current].biome in _LAKE_BIOMES
            and cells[current].elevation < _LAKE_ELEVATION_MAX
            and cells[current].feature is HexFeatureType.NONE
            and not any(
                cells[n].feature is HexFeatureType.LAKE
                for n in neighbors(current)
                if n in cells
            )
            and rng.random() < continental.lake_chance
        ):
            cells[current].feature = HexFeatureType.LAKE
            break

        if len(path) >= params.max_length:
            break

        # Find valid neighbors.
        all_nbrs = [
            n for n in neighbors(current)
            if n in cells and n not in visited
        ]

        # If a WATER neighbor exists, always step into it —
        # the river should reach the sea rather than dying
        # one hex short due to flatness.
        water_nbrs = [
            n for n in all_nbrs
            if cells[n].biome is Biome.WATER
        ]
        if water_nbrs:
            chosen = water_nbrs[0]
            path.append(chosen)
            visited.add(chosen)
            break

        # Also consider visited hexes that carry a river — the
        # new river can merge into an existing one (confluence).
        merge_nbrs = [
            n for n in neighbors(current)
            if n in cells and n in visited
            and any(s.type == "river" for s in cells[n].edges)
        ]
        if not all_nbrs and not merge_nbrs:
            break

        # If only merge targets remain, pick the best one and
        # terminate (confluence).
        if not all_nbrs:
            cur_elev = cells[current].elevation
            best = min(
                merge_nbrs,
                key=lambda n: cells[n].elevation,
            )
            if cells[best].elevation < cur_elev:
                path.append(best)
            break

        # Weight by elevation drop. Forest gets a penalty
        # (0.5x weight multiplier) but is not blocked.
        # WATER neighbors get a strong bonus to pull rivers
        # toward the coast.
        cur_elev = cells[current].elevation
        weights: list[float] = []
        for n in all_nbrs:
            drop = cur_elev - cells[n].elevation
            w = max(drop + rng.uniform(-0.03, 0.03), 0.001)
            if cells[n].biome is Biome.FOREST:
                w *= 0.5
            # Bonus for neighbors adjacent to water (pull
            # toward the coast).
            if any(
                nn in cells and cells[nn].biome is Biome.WATER
                for nn in neighbors(n)
                if nn in cells
            ):
                w += 0.3
            weights.append(w)

        chosen = rng.choices(all_nbrs, weights=weights, k=1)[0]
        path.append(chosen)
        visited.add(chosen)
        current = chosen

        # Flatness termination.
        if len(path) >= params.flatness_window:
            recent_drop = (
                cells[path[-params.flatness_window]].elevation
                - cells[current].elevation
            )
            if recent_drop < params.flatness_threshold:
                break

    return path


def _stamp_edges(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
) -> None:
    """Add ``EdgeSegment(type="river", ...)`` to each cell."""
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
            EdgeSegment(type="river", entry_edge=entry, exit_edge=exit_),
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_rivers_v2(
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    params: RiverParams,
    continental: ContinentalParams,
    flow_count: dict[HexCoord, int],
) -> list[list[HexCoord]]:
    """Generate rivers on the overland map (v2 algorithm).

    Mutates *cells* in place, stamping ``EdgeSegment`` on each
    hex a river crosses. Returns the list of river coord
    sequences (source->sink).
    """
    # Source selection: mountain and hills hexes above elevation
    # floor. Hills are valid secondary sources for rivers that
    # originate in highland plateaus.
    _SOURCE_BIOMES = frozenset({Biome.MOUNTAIN, Biome.HILLS})
    sources = [
        c for c, cell in cells.items()
        if cell.biome in _SOURCE_BIOMES
        and cell.elevation >= params.source_elevation_min
    ]
    if not sources:
        return []

    # Sort by flow count descending (drainage-basin preference),
    # then select sources with minimum spacing so rivers
    # originate from different parts of the map.
    sources.sort(
        key=lambda c: flow_count.get(c, 0), reverse=True,
    )
    min_source_spacing = 4
    selected: list[HexCoord] = []
    for s in sources:
        if len(selected) >= params.max_rivers:
            break
        if all(
            distance(s, prev) >= min_source_spacing
            for prev in selected
        ):
            selected.append(s)
    sources = selected

    rivers: list[list[HexCoord]] = []
    # Global visited prevents rivers from crossing each other.
    visited: set[HexCoord] = set()
    branches: list[HexCoord] = []

    for source in sources:
        if source in visited:
            continue

        path = _trace_river_v2(
            source, cells, rng, visited, params, continental,
        )

        # Bifurcation: collect branch points.
        for step, coord in enumerate(path):
            if step < 3:
                continue
            if rng.random() < params.bifurcation_chance:
                branches.append(coord)

        if len(path) >= params.min_length:
            _stamp_edges(path, cells)
            rivers.append(path)

    # Process branches (share the visited set so they don't
    # cross the main river or each other).
    for branch_src in branches:
        branch = _trace_river_v2(
            branch_src, cells, rng, visited, params, continental,
        )
        if len(branch) >= params.min_length:
            _stamp_edges(branch, cells)
            rivers.append(branch)

    return rivers

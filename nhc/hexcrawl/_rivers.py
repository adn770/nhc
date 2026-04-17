"""River generation for the hexcrawl overland map.

Rivers originate at high-elevation mountain hexes and flow
downhill toward WATER (sea) tiles, tracing an organic path
through the terrain. Each hex along the river carries an
:class:`~nhc.hexcrawl.model.EdgeSegment` with entry/exit edge
indices so the frontend can draw the river as a continuous line
crossing hex edges.

The algorithm:

1. Pick mountain sources above a configurable elevation threshold.
2. Walk downhill with weighted-random neighbour selection (prefer
   steeper descent, add jitter for organic shape).
3. Optionally bifurcate (branch) with low probability per step.
4. Discard rivers shorter than a configurable minimum length.
5. Stamp ``EdgeSegment(type="river", ...)`` on each hex along the
   path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from nhc.hexcrawl.coords import HexCoord, NEIGHBOR_OFFSETS, neighbors
from nhc.hexcrawl.model import Biome, EdgeSegment, HexCell


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RiverParams:
    """Pack-configurable knobs for river generation."""

    max_rivers: int = 3
    min_length: int = 4
    bifurcation_chance: float = 0.05
    source_elevation_min: float = 0.65


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Pre-built offset→index lookup for direction_index.
_OFFSET_TO_IDX: dict[tuple[int, int], int] = {
    offset: i for i, offset in enumerate(NEIGHBOR_OFFSETS)
}


def direction_index(a: HexCoord, b: HexCoord) -> int:
    """Return the NEIGHBOR_OFFSETS index for the step from *a* to *b*.

    Raises :class:`ValueError` if *b* is not a direct neighbour of *a*.
    """
    key = (b.q - a.q, b.r - a.r)
    idx = _OFFSET_TO_IDX.get(key)
    if idx is None:
        raise ValueError(
            f"{b} is not a neighbour of {a} (offset {key})"
        )
    return idx


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def _trace_river(
    source: HexCoord,
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    visited: set[HexCoord],
    params: RiverParams,
) -> list[HexCoord]:
    """Walk downhill from *source*, collecting the river path.

    *visited* is shared across the main river and any branches so
    rivers don't cross each other. Returns the path (which may be
    shorter than ``params.min_length``; the caller filters).
    """
    path: list[HexCoord] = [source]
    visited.add(source)
    current = source

    while True:
        nbrs = [
            n for n in neighbors(current)
            if n in cells and n not in visited
        ]
        if not nbrs:
            break

        # Weight neighbours by elevation drop. Positive drop is
        # downhill (good); negative is uphill (bad). A small jitter
        # prevents perfectly straight rivers on monotone terrain.
        cur_elev = cells[current].elevation
        weights: list[float] = []
        for n in nbrs:
            drop = cur_elev - cells[n].elevation
            w = max(drop + rng.uniform(-0.03, 0.03), 0.001)
            weights.append(w)

        chosen = rng.choices(nbrs, weights=weights, k=1)[0]
        path.append(chosen)
        visited.add(chosen)
        current = chosen

        if cells[current].biome is Biome.WATER:
            break

    return path


def _stamp_edges(
    path: list[HexCoord],
    cells: dict[HexCoord, HexCell],
) -> None:
    """Add ``EdgeSegment(type="river", ...)`` to each cell along *path*."""
    for i, coord in enumerate(path):
        if i == 0:
            entry: int | None = None
        else:
            # Direction from prev to current, then flip to the
            # receiving side.
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


def generate_rivers(
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
    params: RiverParams,
) -> list[list[HexCoord]]:
    """Generate rivers on the overland map.

    Mutates *cells* in place, stamping ``EdgeSegment`` on each hex
    a river crosses. Returns the list of river coord sequences
    (source→sink) for storage on :attr:`HexWorld.rivers`.
    """
    # 1. Source selection: mountain hexes above the elevation floor.
    sources = [
        c for c, cell in cells.items()
        if cell.biome is Biome.MOUNTAIN
        and cell.elevation >= params.source_elevation_min
    ]
    if not sources:
        return []
    rng.shuffle(sources)
    sources = sources[:params.max_rivers]

    rivers: list[list[HexCoord]] = []
    visited: set[HexCoord] = set()
    # Pending branches: (branch_source, visited_snapshot).
    branches: list[HexCoord] = []

    for source in sources:
        if source in visited:
            continue

        path = _trace_river(source, cells, rng, visited, params)

        # Bifurcation: collect branch points along the main river.
        for step, coord in enumerate(path):
            if step < 3:
                continue
            if rng.random() < params.bifurcation_chance:
                branches.append(coord)

        if len(path) >= params.min_length:
            _stamp_edges(path, cells)
            rivers.append(path)

    # Process branches (they share the visited set so they don't
    # cross the main river or each other).
    for branch_src in branches:
        branch = _trace_river(branch_src, cells, rng, visited, params)
        if len(branch) >= params.min_length:
            _stamp_edges(branch, cells)
            rivers.append(branch)

    return rivers

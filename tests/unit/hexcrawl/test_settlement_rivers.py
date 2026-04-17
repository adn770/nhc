"""Tests for river-proximity preference in settlement placement.

Hub and village placement should prefer hexes adjacent to rivers
when rivers exist, falling back to the standard placement when
no river-adjacent candidates are available.
"""

from __future__ import annotations

import random

import pytest

from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    EdgeSegment,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl._features import pick_hub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_grid(
    width: int = 8,
    height: int = 8,
) -> dict[Biome, list[HexCoord]]:
    """Return a hexes_by_biome dict for a uniform greenlands grid."""
    hbb: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
    for q in range(width):
        for r in range(height):
            hbb[Biome.GREENLANDS].append(HexCoord(q, r))
    return hbb


def _make_cells_with_river(
    width: int = 8,
    height: int = 8,
) -> dict[HexCoord, HexCell]:
    """Greenlands grid with a vertical river at q=4."""
    cells: dict[HexCoord, HexCell] = {}
    for q in range(width):
        for r in range(height):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=Biome.GREENLANDS,
                elevation=0.3,
            )
    # Stamp a river along q=4.
    for r in range(height):
        entry = None if r == 0 else 0
        exit_ = None if r == height - 1 else 3
        cells[HexCoord(4, r)].edges.append(
            EdgeSegment(type="river", entry_edge=entry, exit_edge=exit_),
        )
    return cells


def _has_river(cell: HexCell) -> bool:
    return any(s.type == "river" for s in cell.edges)


def _near_river(
    coord: HexCoord,
    cells: dict[HexCoord, HexCell],
) -> bool:
    """True if coord or any of its neighbours has a river segment."""
    if _has_river(cells[coord]):
        return True
    for n in neighbors(coord):
        if n in cells and _has_river(cells[n]):
            return True
    return False


# ---------------------------------------------------------------------------
# Hub placement
# ---------------------------------------------------------------------------


def test_hub_prefers_river_adjacent(
) -> None:
    """When river-adjacent greenlands exist, hub should land near one."""
    cells = _make_cells_with_river()
    hexes_by_biome = {b: [] for b in Biome}
    for c in cells.values():
        hexes_by_biome[c.biome].append(c.coord)

    # Run many seeds; the hub should consistently land near the
    # river (within distance 1 of a river hex).
    near_count = 0
    trials = 50
    for seed in range(trials):
        rng = random.Random(seed)
        hub = pick_hub(hexes_by_biome, rng, cells)
        if hub is not None and _near_river(hub, cells):
            near_count += 1
    # At least 80% of the time the hub should be near a river.
    assert near_count >= trials * 0.8, (
        f"hub near river only {near_count}/{trials} times"
    )


def test_hub_falls_back_without_rivers() -> None:
    """Without rivers, hub still lands in greenlands/drylands."""
    cells: dict[HexCoord, HexCell] = {}
    for q in range(4):
        for r in range(4):
            cells[HexCoord(q, r)] = HexCell(
                coord=HexCoord(q, r),
                biome=Biome.GREENLANDS,
                elevation=0.3,
            )
    hexes_by_biome = {b: [] for b in Biome}
    for c in cells.values():
        hexes_by_biome[c.biome].append(c.coord)
    rng = random.Random(42)
    hub = pick_hub(hexes_by_biome, rng, cells)
    assert hub is not None
    assert cells[hub].biome is Biome.GREENLANDS

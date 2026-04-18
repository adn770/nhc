"""Scored settlement placement for the continental generator.

Places settlements using a scoring function that prefers
geographically advantageous locations: biome borders, river
proximity, lake proximity, biome suitability, and mid-elevation.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import FeatureTargets
from nhc.hexcrawl._biome_data import (
    BIOME_SETTLEMENT_BONUS,
    CANDIDATE_BIOMES,
    SETTLEMENT_FEATURES,
)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def settlement_score(
    coord: HexCoord,
    cells: dict[HexCoord, HexCell],
) -> float:
    """Score a hex for settlement suitability."""
    score = 0.0
    cell = cells[coord]

    # 1. Biome border bonus: +3 per distinct neighbor biome.
    neighbor_biomes = {
        cells[n].biome
        for n in neighbors(coord)
        if n in cells
    }
    score += 3.0 * len(neighbor_biomes - {cell.biome})

    # 2. River proximity: +5 if on a river, +3 if adjacent.
    has_river = any(s.type == "river" for s in cell.edges)
    if has_river:
        score += 5.0
    elif any(
        any(s.type == "river" for s in cells[n].edges)
        for n in neighbors(coord)
        if n in cells
    ):
        score += 3.0

    # 3. Lake proximity: +4 if adjacent to a lake.
    for n in neighbors(coord):
        if n in cells and cells[n].feature is HexFeatureType.LAKE:
            score += 4.0
            break

    # 4. Biome suitability.
    score += BIOME_SETTLEMENT_BONUS.get(cell.biome, 0.0)

    # 5. Elevation preference: mid-elevation is best.
    if 0.15 <= cell.elevation <= 0.45:
        score += 1.0

    return score


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------


def _adjacent_to_settlement(
    coord: HexCoord,
    cells: dict[HexCoord, HexCell],
) -> bool:
    """True if any neighbor already has a settlement feature."""
    for n in neighbors(coord):
        if n in cells and cells[n].feature in SETTLEMENT_FEATURES:
            return True
    return False


def place_settlements(
    cells: dict[HexCoord, HexCell],
    targets: FeatureTargets,
    rng: random.Random,
) -> HexCoord | None:
    """Place hub, cities, and villages using scored placement.

    Mutates *cells* in place. Returns the hub coordinate.
    """
    # Score all candidate hexes.
    candidates: list[tuple[float, HexCoord]] = []
    for coord, cell in cells.items():
        if cell.biome not in CANDIDATE_BIOMES:
            continue
        if cell.feature is not HexFeatureType.NONE:
            continue
        score = settlement_score(coord, cells)
        candidates.append((score, coord))

    # Sort by score descending; break ties by coordinate for
    # determinism.
    candidates.sort(key=lambda x: (-x[0], x[1].q, x[1].r))

    # Place hub: highest-scoring GREENLANDS hex.
    hub: HexCoord | None = None
    for _, coord in candidates:
        if cells[coord].biome is Biome.GREENLANDS:
            cells[coord].feature = HexFeatureType.CITY
            hub = coord
            break

    # Place remaining settlements.
    placed = 0
    target_count = rng.randint(
        targets.village.min, targets.village.max,
    )
    for _, coord in candidates:
        if placed >= target_count:
            break
        if cells[coord].feature is not HexFeatureType.NONE:
            continue
        if _adjacent_to_settlement(coord, cells):
            continue
        # First placed settlement is a city, rest are villages.
        if placed == 0 and hub is not None:
            cells[coord].feature = HexFeatureType.VILLAGE
        else:
            cells[coord].feature = HexFeatureType.VILLAGE
        placed += 1

    return hub

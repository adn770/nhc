"""Hex flower generation for the sub-hex exploration layer.

Each macro hex gets a 19-cell hex flower (radius 2) of sub-hexes.
This module handles biome blending, river/road sub-hex routing,
feature scattering, and fast-travel cost pre-computation.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import (
    HexCoord,
    NEIGHBOR_OFFSETS,
    distance,
    neighbors,
)
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    EDGE_TO_RING2,
    FLOWER_COORDS,
    FLOWER_RADIUS,
)


# ---------------------------------------------------------------------------
# Biome transition table
# ---------------------------------------------------------------------------

# When blending at ring-2, a (parent, neighbor) pair may produce
# an intermediate "transition" biome instead of either endpoint.
# Missing pairs fall through to the neighbor biome directly.

_BIOME_TRANSITIONS: dict[tuple[Biome, Biome], Biome] = {
    (Biome.FOREST, Biome.MOUNTAIN): Biome.HILLS,
    (Biome.MOUNTAIN, Biome.FOREST): Biome.HILLS,
    (Biome.GREENLANDS, Biome.MOUNTAIN): Biome.HILLS,
    (Biome.MOUNTAIN, Biome.GREENLANDS): Biome.HILLS,
    (Biome.GREENLANDS, Biome.MARSH): Biome.SWAMP,
    (Biome.MARSH, Biome.GREENLANDS): Biome.SWAMP,
    (Biome.GREENLANDS, Biome.SWAMP): Biome.MARSH,
    (Biome.SWAMP, Biome.GREENLANDS): Biome.MARSH,
    (Biome.MOUNTAIN, Biome.ICELANDS): Biome.HILLS,
    (Biome.ICELANDS, Biome.MOUNTAIN): Biome.HILLS,
    (Biome.DRYLANDS, Biome.SANDLANDS): Biome.SANDLANDS,
    (Biome.SANDLANDS, Biome.DRYLANDS): Biome.DRYLANDS,
    (Biome.FOREST, Biome.GREENLANDS): Biome.FOREST,
    (Biome.GREENLANDS, Biome.FOREST): Biome.FOREST,
}


# Ring-1 "family variant" table: parent biome → possible variant.
# 15% chance per ring-1 cell to get one of these instead.

_RING1_VARIANTS: dict[Biome, list[Biome]] = {
    Biome.FOREST: [Biome.HILLS, Biome.GREENLANDS],
    Biome.MOUNTAIN: [Biome.HILLS],
    Biome.GREENLANDS: [Biome.FOREST],
    Biome.HILLS: [Biome.MOUNTAIN, Biome.GREENLANDS],
    Biome.MARSH: [Biome.SWAMP],
    Biome.SWAMP: [Biome.MARSH],
    Biome.DRYLANDS: [Biome.SANDLANDS],
    Biome.SANDLANDS: [Biome.DRYLANDS],
}


# ---------------------------------------------------------------------------
# Sub-hex → macro edge mapping (for ring-2 blending)
# ---------------------------------------------------------------------------

# Invert EDGE_TO_RING2: for each ring-2 sub-hex, which macro
# edge(s) it belongs to. A sub-hex may map to one edge.
_RING2_TO_EDGE: dict[HexCoord, int] = {}
for _edge, _pair in EDGE_TO_RING2.items():
    for _h in _pair:
        _RING2_TO_EDGE[_h] = _edge


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assign_sub_hex_biomes(
    parent: HexCell,
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
) -> dict[HexCoord, Biome]:
    """Assign biomes to all 19 sub-hex positions in the flower.

    * Ring 0: always inherits parent biome.
    * Ring 1: parent biome with 15% chance of a family variant.
    * Ring 2: blends toward adjacent macro hex biomes.

    Parameters
    ----------
    parent : HexCell
        The macro hex this flower belongs to.
    cells : dict[HexCoord, HexCell]
        All macro hex cells on the map (for neighbor lookups).
    rng : random.Random
        Seeded RNG for determinism.

    Returns
    -------
    dict[HexCoord, Biome]
        Map from local flower coord → biome for all 19 cells.
    """
    center = HexCoord(0, 0)
    result: dict[HexCoord, Biome] = {}

    for c in FLOWER_COORDS:
        d = distance(center, c)
        if d == 0:
            result[c] = parent.biome
        elif d == 1:
            result[c] = _ring1_biome(parent.biome, rng)
        else:
            result[c] = _ring2_biome(parent, c, cells, rng)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ring1_biome(parent_biome: Biome, rng: random.Random) -> Biome:
    """Ring 1: parent biome with 15% chance of family variant."""
    variants = _RING1_VARIANTS.get(parent_biome)
    if variants and rng.random() < 0.15:
        return rng.choice(variants)
    return parent_biome


def _ring2_biome(
    parent: HexCell,
    sub_coord: HexCoord,
    cells: dict[HexCoord, HexCell],
    rng: random.Random,
) -> Biome:
    """Ring 2: blend toward the macro neighbor biome at this edge.

    * 50% parent biome
    * 40% neighbor biome (if different)
    * 10% transition biome from the lookup table
    * Falls back to parent if no neighbor exists (map edge).
    """
    edge = _RING2_TO_EDGE.get(sub_coord)
    if edge is None:
        return parent.biome

    # Find the macro neighbor in this direction
    dq, dr = NEIGHBOR_OFFSETS[edge]
    neighbor_coord = HexCoord(parent.coord.q + dq, parent.coord.r + dr)
    neighbor = cells.get(neighbor_coord)

    if neighbor is None or neighbor.biome == parent.biome:
        return parent.biome

    roll = rng.random()
    if roll < 0.50:
        return parent.biome
    elif roll < 0.90:
        return neighbor.biome
    else:
        transition = _BIOME_TRANSITIONS.get(
            (parent.biome, neighbor.biome),
        )
        return transition if transition is not None else neighbor.biome

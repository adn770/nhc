"""Hex flower generation for the sub-hex exploration layer.

Each macro hex gets a 19-cell hex flower (radius 2) of sub-hexes.
This module handles biome blending, river/road sub-hex routing,
feature scattering, and fast-travel cost pre-computation.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from nhc.hexcrawl.coords import (
    HexCoord,
    NEIGHBOR_OFFSETS,
    distance,
    neighbors,
)
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
    MinorFeatureType,
    SubHexCell,
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


# ---------------------------------------------------------------------------
# River / road routing through the flower (mini A*)
# ---------------------------------------------------------------------------


def _flower_astar(
    cells: dict[HexCoord, "SubHexCell"],
    start: HexCoord,
    goal: HexCoord,
    step_cost: "Callable[[HexCoord, HexCoord], float] | None" = None,
) -> list[HexCoord]:
    """A* through the 19-cell flower from *start* to *goal*.

    *step_cost*, if provided, is called as ``step_cost(from, to)``
    to get the edge weight. Defaults to uniform 1.0.
    Returns the path including both endpoints.
    """
    import heapq

    open_set: list[tuple[float, int, HexCoord]] = []
    counter = 0
    heapq.heappush(open_set, (0.0, counter, start))
    came_from: dict[HexCoord, HexCoord] = {}
    g_score: dict[HexCoord, float] = {start: 0.0}

    while open_set:
        _, _, current = heapq.heappop(open_set)
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path

        for n in neighbors(current):
            if n not in cells:
                continue
            w = step_cost(current, n) if step_cost else 1.0
            tentative = g_score[current] + w
            if tentative < g_score.get(n, float("inf")):
                came_from[n] = current
                g_score[n] = tentative
                h = distance(n, goal)
                counter += 1
                heapq.heappush(open_set, (tentative + h, counter, n))

    # Fallback: should not happen in a connected 19-cell flower
    return [start, goal]


def route_river_through_flower(
    cells: dict[HexCoord, "SubHexCell"],
    entry_edge: int | None,
    exit_edge: int | None,
    rng: random.Random,
    *,
    mark_cells: bool = False,
) -> list[HexCoord]:
    """Route a river (or road) through the flower.

    Parameters
    ----------
    cells : dict[HexCoord, SubHexCell]
        The 19 sub-hex cells of the flower.
    entry_edge : int | None
        Macro edge index (0-5) the river enters from, or None for
        a river source (starts at ring 1).
    exit_edge : int | None
        Macro edge index the river exits to, or None for a sink
        (ends at ring 1).
    rng : random.Random
        Seeded RNG for picking among entry/exit options.
    mark_cells : bool
        If True, set ``has_river = True`` on crossed sub-hexes.

    Returns
    -------
    list[HexCoord]
        Ordered sub-hex coords from entry to exit.
    """
    center = HexCoord(0, 0)

    # Pick start sub-hex
    if entry_edge is not None:
        start_options = list(EDGE_TO_RING2[entry_edge])
        start = rng.choice(start_options)
    else:
        # Source: pick a ring-1 sub-hex
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        start = rng.choice(ring1)

    # Pick goal sub-hex
    if exit_edge is not None:
        goal_options = list(EDGE_TO_RING2[exit_edge])
        goal = rng.choice(goal_options)
    else:
        # Sink: pick a ring-1 sub-hex (different from start if possible)
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        candidates = [c for c in ring1 if c != start]
        goal = rng.choice(candidates) if candidates else ring1[0]

    path = _flower_astar(cells, start, goal)

    if mark_cells:
        for c in path:
            cells[c].has_river = True

    return path


def route_road_through_flower(
    cells: dict[HexCoord, "SubHexCell"],
    entry_edge: int,
    exit_edge: int,
    rng: random.Random,
    *,
    feature_cell: HexCoord | None = None,
    mark_cells: bool = False,
) -> list[HexCoord]:
    """Route a road through the flower, preferring the feature cell.

    Parameters
    ----------
    cells : dict[HexCoord, SubHexCell]
        The 19 sub-hex cells of the flower.
    entry_edge, exit_edge : int
        Macro edge indices (0-5).
    rng : random.Random
        Seeded RNG for picking among entry/exit options.
    feature_cell : HexCoord | None
        If set, the A* cost function gives a strong bonus for
        stepping onto this cell (roads lead to the feature).
    mark_cells : bool
        If True, set ``has_road = True`` and halve
        ``move_cost_hours`` on crossed sub-hexes.
    """
    start_options = list(EDGE_TO_RING2[entry_edge])
    start = rng.choice(start_options)
    goal_options = list(EDGE_TO_RING2[exit_edge])
    goal = rng.choice(goal_options)

    # Cost function: stepping onto the feature cell is cheap (0.1)
    # so A* routes through it when it doesn't add too much detour.
    def step_cost(_from: HexCoord, to: HexCoord) -> float:
        if feature_cell is not None and to == feature_cell:
            return 0.1
        return 1.0

    path = _flower_astar(cells, start, goal, step_cost=step_cost)

    if mark_cells:
        for c in path:
            cells[c].has_road = True
            cells[c].move_cost_hours = max(
                0.5, cells[c].move_cost_hours / 2,
            )

    return path


# ---------------------------------------------------------------------------
# Feature placement
# ---------------------------------------------------------------------------

# Biome → (min, max) minor features per flower.
_MINOR_DENSITY: dict[Biome, tuple[int, int]] = {
    Biome.GREENLANDS: (3, 6),
    Biome.FOREST: (2, 5),
    Biome.DRYLANDS: (2, 4),
    Biome.HILLS: (2, 4),
    Biome.MARSH: (2, 4),
    Biome.SWAMP: (2, 4),
    Biome.MOUNTAIN: (1, 3),
    Biome.SANDLANDS: (1, 3),
    Biome.DEADLANDS: (1, 3),
    Biome.ICELANDS: (1, 2),
    Biome.WATER: (0, 0),
}

# Biome → pool of eligible minor feature types.
_MINOR_POOLS: dict[Biome, list[MinorFeatureType]] = {
    Biome.GREENLANDS: [
        MinorFeatureType.FARM, MinorFeatureType.WELL,
        MinorFeatureType.SHRINE, MinorFeatureType.SIGNPOST,
        MinorFeatureType.CAMPSITE, MinorFeatureType.ORCHARD,
    ],
    Biome.FOREST: [
        MinorFeatureType.HERB_PATCH, MinorFeatureType.MUSHROOM_RING,
        MinorFeatureType.HOLLOW_LOG, MinorFeatureType.CAIRN,
        MinorFeatureType.STANDING_STONE,
    ],
    Biome.MOUNTAIN: [
        MinorFeatureType.CAIRN, MinorFeatureType.BONE_PILE,
        MinorFeatureType.STANDING_STONE,
    ],
    Biome.HILLS: [
        MinorFeatureType.CAIRN, MinorFeatureType.CAMPSITE,
        MinorFeatureType.STANDING_STONE, MinorFeatureType.HERB_PATCH,
    ],
    Biome.DRYLANDS: [
        MinorFeatureType.WELL, MinorFeatureType.CAIRN,
        MinorFeatureType.CAMPSITE, MinorFeatureType.SIGNPOST,
    ],
    Biome.SANDLANDS: [
        MinorFeatureType.CAIRN, MinorFeatureType.BONE_PILE,
        MinorFeatureType.WELL,
    ],
    Biome.ICELANDS: [
        MinorFeatureType.CAIRN, MinorFeatureType.STANDING_STONE,
    ],
    Biome.DEADLANDS: [
        MinorFeatureType.BONE_PILE, MinorFeatureType.STANDING_STONE,
        MinorFeatureType.CAIRN,
    ],
    Biome.MARSH: [
        MinorFeatureType.HOLLOW_LOG, MinorFeatureType.MUSHROOM_RING,
        MinorFeatureType.HERB_PATCH,
    ],
    Biome.SWAMP: [
        MinorFeatureType.HOLLOW_LOG, MinorFeatureType.MUSHROOM_RING,
        MinorFeatureType.BONE_PILE,
    ],
    Biome.WATER: [],
}

# Biome → probability of placing a lair.
_LAIR_CHANCE: dict[Biome, float] = {
    Biome.DEADLANDS: 0.40,
    Biome.MOUNTAIN: 0.30,
    Biome.FOREST: 0.20,
    Biome.HILLS: 0.15,
    Biome.MARSH: 0.15,
    Biome.SWAMP: 0.15,
    Biome.ICELANDS: 0.10,
    Biome.DRYLANDS: 0.10,
    Biome.SANDLANDS: 0.10,
    Biome.GREENLANDS: 0.05,
}

_LAIR_TYPES = [
    MinorFeatureType.LAIR,
    MinorFeatureType.NEST,
    MinorFeatureType.BURROW,
]


def place_flower_features(
    cells: dict[HexCoord, SubHexCell],
    major: HexFeatureType,
    biome: Biome,
    rng: random.Random,
) -> HexCoord | None:
    """Place major and minor features in the flower.

    Returns the sub-hex coord of the major feature, or None if
    the major feature type is NONE.
    """
    center = HexCoord(0, 0)
    feature_cell: HexCoord | None = None

    # --- Major feature ---
    if major is not HexFeatureType.NONE:
        feature_cell = _place_major(cells, major, rng)

    # --- Minor features ---
    lo, hi = _MINOR_DENSITY.get(biome, (0, 0))
    count = rng.randint(lo, hi) if hi > 0 else 0
    pool = _MINOR_POOLS.get(biome, [])
    if count > 0 and pool:
        _place_minors(cells, count, pool, feature_cell, rng)

    # --- Lair ---
    lair_prob = _LAIR_CHANCE.get(biome, 0.0)
    if lair_prob > 0 and rng.random() < lair_prob:
        _place_lair(cells, feature_cell, rng)

    return feature_cell


def _place_major(
    cells: dict[HexCoord, SubHexCell],
    major: HexFeatureType,
    rng: random.Random,
) -> HexCoord:
    """Place the macro feature in a weighted-random sub-hex."""
    center = HexCoord(0, 0)
    # Build weighted candidates: ring 0 = 3, ring 1 = 5, ring 2 = 1
    ring_weights = {0: 3, 1: 5, 2: 1}
    candidates: list[HexCoord] = []
    weights: list[int] = []
    for c in FLOWER_COORDS:
        d = distance(center, c)
        cell = cells[c]
        if cell.has_river:
            continue
        candidates.append(c)
        weights.append(ring_weights[d])

    if not candidates:
        # Fallback: all sub-hexes have rivers (very unlikely)
        candidates = list(FLOWER_COORDS)
        weights = [1] * len(candidates)

    chosen = rng.choices(candidates, weights=weights, k=1)[0]
    cells[chosen].major_feature = major
    return chosen


def _place_minors(
    cells: dict[HexCoord, SubHexCell],
    count: int,
    pool: list[MinorFeatureType],
    feature_cell: HexCoord | None,
    rng: random.Random,
) -> None:
    """Scatter minor features, avoiding feature cell and rivers/roads."""
    eligible = [
        c for c in FLOWER_COORDS
        if c != feature_cell
        and not cells[c].has_river
        and not cells[c].has_road
        and cells[c].minor_feature is MinorFeatureType.NONE
    ]
    rng.shuffle(eligible)
    placed = 0
    for c in eligible:
        if placed >= count:
            break
        cells[c].minor_feature = rng.choice(pool)
        placed += 1


def _place_lair(
    cells: dict[HexCoord, SubHexCell],
    feature_cell: HexCoord | None,
    rng: random.Random,
) -> None:
    """Place at most one lair in ring 2."""
    center = HexCoord(0, 0)
    eligible = [
        c for c in FLOWER_COORDS
        if distance(center, c) == 2
        and c != feature_cell
        and not cells[c].has_river
        and not cells[c].has_road
        and cells[c].minor_feature is MinorFeatureType.NONE
    ]
    if not eligible:
        return
    chosen = rng.choice(eligible)
    cells[chosen].minor_feature = rng.choice(_LAIR_TYPES)
    cells[chosen].encounter_modifier = 3.0

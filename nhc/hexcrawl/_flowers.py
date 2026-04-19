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
    HexFlower,
    MinorFeatureType,
    SubHexCell,
    SubHexEdgeSegment,
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


def get_exit_edge(
    sub_from: HexCoord,
    sub_to: HexCoord,
) -> int | None:
    """Determine the macro exit edge when stepping out of the flower.

    Returns the macro edge index (0-5) if *sub_from* is a ring-2
    hex and *sub_to* is outside the flower in the direction of
    that edge. Returns ``None`` if this is an interior move.
    """
    if sub_to in FLOWER_COORDS:
        return None
    edge = _RING2_TO_EDGE.get(sub_from)
    if edge is None:
        return None
    # Verify the step direction matches the edge direction
    dq, dr = NEIGHBOR_OFFSETS[edge]
    expected = HexCoord(sub_from.q + dq, sub_from.r + dr)
    if sub_to == expected:
        return edge
    # The sub-hex is on this edge but the player is stepping
    # in a different outward direction — find which edge that is.
    step = (sub_to.q - sub_from.q, sub_to.r - sub_from.r)
    for d in range(6):
        if NEIGHBOR_OFFSETS[d] == step:
            # Check if this direction actually exits the flower
            target = HexCoord(sub_from.q + step[0], sub_from.r + step[1])
            if target not in FLOWER_COORDS:
                return d
    return None


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

    # Never place WATER sub-hexes inside a land flower — ring-2
    # blending toward an ocean neighbor can produce them.
    for c in FLOWER_COORDS:
        if result[c] is Biome.WATER:
            result[c] = parent.biome

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
    trunk_cells: frozenset[HexCoord] | set[HexCoord] | None = None,
) -> list[HexCoord]:
    """Route a river through the flower.

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
    trunk_cells : set[HexCoord] | None
        Sub-cells already occupied by an earlier river in the same
        flower. When provided, A* strongly prefers these cells so
        a later river merges into the trunk at a confluence
        instead of drawing a second parallel line.
    """
    center = HexCoord(0, 0)

    # Pick start sub-hex. Prefer a cell already on the trunk so
    # the new river shares the entry point with the earlier one.
    if entry_edge is not None:
        start_options = list(EDGE_TO_RING2[entry_edge])
        on_trunk = [c for c in start_options if trunk_cells and c in trunk_cells]
        start = rng.choice(on_trunk or start_options)
    else:
        # Source: pick a ring-1 sub-hex (preferably already trunk
        # so the source joins the existing flow immediately).
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        on_trunk = [c for c in ring1 if trunk_cells and c in trunk_cells]
        start = rng.choice(on_trunk or ring1)

    # Pick goal sub-hex. Same preference -- a trunk cell on the
    # same edge wins so the merge happens at the shared exit.
    if exit_edge is not None:
        goal_options = list(EDGE_TO_RING2[exit_edge])
        on_trunk = [c for c in goal_options if trunk_cells and c in trunk_cells]
        goal = rng.choice(on_trunk or goal_options)
    else:
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        candidates = [c for c in ring1 if c != start]
        on_trunk = [c for c in candidates if trunk_cells and c in trunk_cells]
        pool = on_trunk or candidates or ring1
        goal = rng.choice(pool)

    # Penalise center (ring 0) so rivers don't obscure feature
    # icons, and forest sub-hexes so rivers flow through
    # clearings and lighter vegetation instead. Trunk cells of a
    # prior river are heavily discounted so the new river merges.
    def river_cost(_from: HexCoord, to: HexCoord) -> float:
        if trunk_cells and to in trunk_cells:
            return 0.05
        if to == center:
            return 5.0
        if cells[to].biome is Biome.FOREST:
            return 5.0
        return 1.0

    path = _flower_astar(cells, start, goal, step_cost=river_cost)

    if mark_cells:
        for c in path:
            cells[c].has_river = True

    return path


def route_road_through_flower(
    cells: dict[HexCoord, "SubHexCell"],
    entry_edge: int | None,
    exit_edge: int | None,
    rng: random.Random,
    *,
    feature_cell: HexCoord | None = None,
    mark_cells: bool = False,
    trunk_cells: frozenset[HexCoord] | set[HexCoord] | None = None,
) -> list[HexCoord]:
    """Route a road through the flower, preferring the feature cell.

    Parameters
    ----------
    cells : dict[HexCoord, SubHexCell]
        The 19 sub-hex cells of the flower.
    entry_edge, exit_edge : int | None
        Macro edge indices (0-5), or None for paths that
        originate/terminate at this hex's feature.
    rng : random.Random
        Seeded RNG for picking among entry/exit options.
    feature_cell : HexCoord | None
        If set, the A* cost function gives a strong bonus for
        stepping onto this cell (roads lead to the feature).
    mark_cells : bool
        If True, set ``has_road = True`` and halve
        ``move_cost_hours`` on crossed sub-hexes.
    trunk_cells : set[HexCoord] | None
        Sub-cells already occupied by an earlier road heading to
        the same macro exit. When provided, A* strongly prefers
        these cells so the new road joins the trunk instead of
        laying a parallel path.
    """
    center = HexCoord(0, 0)

    if entry_edge is not None:
        start_options = list(EDGE_TO_RING2[entry_edge])
        start = rng.choice(start_options)
    elif feature_cell is not None:
        start = feature_cell
    else:
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        start = rng.choice(ring1)

    if exit_edge is not None:
        goal_options = list(EDGE_TO_RING2[exit_edge])
        goal = rng.choice(goal_options)
    elif feature_cell is not None:
        goal = feature_cell
    else:
        ring1 = [c for c in FLOWER_COORDS if distance(center, c) == 1]
        candidates = [c for c in ring1 if c != start]
        goal = rng.choice(candidates) if candidates else ring1[0]

    # Cost function: stepping onto the feature cell is cheap (0.1)
    # so A* routes through it when it doesn't add too much detour.
    # Forest sub-hexes are penalised so roads route around them.
    # Trunk cells of a prior road to the same exit are even
    # cheaper so a second road merges into them.
    _ROAD_AVOID = frozenset({Biome.FOREST})

    def step_cost(_from: HexCoord, to: HexCoord) -> float:
        if trunk_cells and to in trunk_cells:
            return 0.05
        if feature_cell is not None and to == feature_cell:
            return 0.1
        if cells[to].biome in _ROAD_AVOID:
            return 4.0
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


# ---------------------------------------------------------------------------
# Fast-travel cost pre-computation
# ---------------------------------------------------------------------------


def compute_fast_travel_costs(
    cells: dict[HexCoord, SubHexCell],
) -> dict[tuple[int, int], float]:
    """Pre-compute A* travel costs for all 30 (entry, exit) pairs.

    Returns a dict mapping ``(entry_edge, exit_edge)`` → cost in
    hours, where the cost is the sum of ``move_cost_hours`` along
    the cheapest path through the flower.
    """
    result: dict[tuple[int, int], float] = {}

    for entry in range(6):
        for exit_ in range(6):
            if entry == exit_:
                continue
            # Try all combinations of entry/exit sub-hexes and
            # keep the cheapest.
            best = float("inf")
            for start in EDGE_TO_RING2[entry]:
                for goal in EDGE_TO_RING2[exit_]:
                    path = _flower_astar(
                        cells, start, goal,
                        step_cost=lambda _f, t: cells[t].move_cost_hours,
                    )
                    cost = sum(cells[c].move_cost_hours for c in path)
                    if cost < best:
                        best = cost
            result[(entry, exit_)] = best

    return result


# ---------------------------------------------------------------------------
# Sub-hex biome → move cost
# ---------------------------------------------------------------------------

_SUB_HEX_BIOME_HOURS: dict[Biome, float] = {
    Biome.GREENLANDS: 1.0,
    Biome.DRYLANDS: 1.0,
    Biome.FOREST: 1.5,
    Biome.HILLS: 1.5,
    Biome.ICELANDS: 1.5,
    Biome.SANDLANDS: 1.5,
    Biome.DEADLANDS: 1.5,
    Biome.MARSH: 2.0,
    Biome.SWAMP: 2.0,
    Biome.MOUNTAIN: 3.0,
    Biome.WATER: 99.0,
}


# ---------------------------------------------------------------------------
# Trunk-trim helper (shared by river and road merge passes)
# ---------------------------------------------------------------------------


def _trim_against_trunk(
    path: list[HexCoord],
    claimed: set[HexCoord],
    entry_edge: int | None,
    exit_edge: int | None,
) -> tuple[list[HexCoord] | None, int | None, int | None]:
    """Trim ``path`` so it shares at most one anchor cell with an
    existing ``claimed`` set of trunk cells.

    Returns ``(trimmed_path, new_entry, new_exit)``. When
    ``trimmed_path`` is ``None`` the segment is fully subsumed by
    the trunk and should be dropped entirely. Entry / exit macro
    edges are cleared when the corresponding end of the path was
    chopped away (the segment now starts or ends interior, at the
    anchor on the trunk instead of at a macro edge).

    Strategy: find the longest claimed prefix and suffix of
    ``path``. Keep one anchor cell in each (the last claimed
    prefix cell, the first claimed suffix cell) so the branch
    visibly connects to the trunk at the junction.
    """
    if not claimed:
        return list(path), entry_edge, exit_edge
    trimmed = list(path)
    first_new = 0
    while (
        first_new < len(trimmed)
        and trimmed[first_new] in claimed
    ):
        first_new += 1
    last_new = len(trimmed) - 1
    while last_new >= 0 and trimmed[last_new] in claimed:
        last_new -= 1
    if first_new > last_new:
        return None, None, None
    start = max(0, first_new - 1)
    end = min(len(trimmed), last_new + 2)
    trimmed = trimmed[start:end]
    new_entry = entry_edge if start == 0 else None
    new_exit = exit_edge if end == len(path) else None
    return trimmed, new_entry, new_exit


# ---------------------------------------------------------------------------
# Orchestrator: generate one flower for a macro hex
# ---------------------------------------------------------------------------


def generate_flower(
    parent: HexCell,
    all_cells: dict[HexCoord, HexCell],
    seed: int,
) -> HexFlower:
    """Generate the complete hex flower for *parent*.

    Runs biome blending, river/road routing, feature placement,
    and fast-travel cost computation.

    Parameters
    ----------
    parent : HexCell
        The macro hex cell to generate a flower for.
    all_cells : dict[HexCoord, HexCell]
        Full macro map cells (for neighbor biome lookups).
    seed : int
        Seed for deterministic generation.
    """
    rng = random.Random(seed)

    # 1. Biome assignment
    biomes = assign_sub_hex_biomes(parent, all_cells, rng)

    # 2. Build sub-hex cells with biome-derived move costs
    cells: dict[HexCoord, SubHexCell] = {}
    center = HexCoord(0, 0)
    for c in FLOWER_COORDS:
        biome = biomes[c]
        d = distance(center, c)
        # Elevation: ring 0 = parent, ring 1 = jitter, ring 2 = blend
        if d == 0:
            elev = parent.elevation
        elif d == 1:
            elev = parent.elevation + rng.uniform(-0.02, 0.02)
        else:
            elev = parent.elevation + rng.uniform(-0.04, 0.04)
        cells[c] = SubHexCell(
            coord=c,
            biome=biome,
            elevation=elev,
            move_cost_hours=_SUB_HEX_BIOME_HOURS.get(biome, 1.0),
        )

    # 3. Route rivers through sub-hexes. A second river with a
    # shared entry/exit or a source flowing into an existing
    # trunk is A*-biased onto the already-claimed sub-cells and
    # then trimmed so two rivers never draw the same sub-cell
    # except at one anchor (the confluence). Mirrors the road
    # merge pass in step 5.
    edge_segments: list[SubHexEdgeSegment] = []
    river_claimed: set[HexCoord] = set()
    for seg in parent.edges:
        if seg.type != "river":
            continue
        path = route_river_through_flower(
            cells,
            entry_edge=seg.entry_edge,
            exit_edge=seg.exit_edge,
            rng=rng,
            mark_cells=True,
            trunk_cells=river_claimed if river_claimed else None,
        )
        trimmed, new_entry, new_exit = _trim_against_trunk(
            path, river_claimed,
            seg.entry_edge, seg.exit_edge,
        )
        if trimmed is None:
            continue
        edge_segments.append(SubHexEdgeSegment(
            type="river",
            path=trimmed,
            entry_macro_edge=new_entry,
            exit_macro_edge=new_exit,
        ))
        river_claimed.update(trimmed)

    # 4. Place major feature
    feature_cell = place_flower_features(
        cells,
        major=parent.feature,
        biome=parent.biome,
        rng=rng,
    )

    # 5. Route roads through sub-hexes (after feature placement
    # so roads can target the feature cell). A* for each new road
    # is biased toward cells already owned by a previously-placed
    # road; afterwards the new sub-path is trimmed so no cell is
    # drawn by more than one segment. Without trimming, hub hexes
    # with three sources/sinks converging on the feature cell
    # stamp the same trunk sub-cells two or three times and the
    # renderer draws overlapping curves on top of each other --
    # the "doubled road near the town" case reported from the
    # live session.
    claimed: set[HexCoord] = set()
    for seg in parent.edges:
        if seg.type != "path":
            continue
        path = route_road_through_flower(
            cells,
            entry_edge=seg.entry_edge,
            exit_edge=seg.exit_edge,
            rng=rng,
            feature_cell=feature_cell,
            mark_cells=True,
            trunk_cells=claimed if claimed else None,
        )
        trimmed, new_entry, new_exit = _trim_against_trunk(
            path, claimed, seg.entry_edge, seg.exit_edge,
        )
        if trimmed is None:
            continue
        edge_segments.append(SubHexEdgeSegment(
            type="path",
            path=trimmed,
            entry_macro_edge=new_entry,
            exit_macro_edge=new_exit,
        ))
        claimed.update(trimmed)

    # 6. Tile slots: assign after rivers/roads so waterway
    # sub-hexes get lighter tile variants.
    from nhc.hexcrawl.tiles import assign_tile_slot
    for c, sc in cells.items():
        has_ww = sc.has_river or sc.has_road
        sc.tile_slot = assign_tile_slot(
            sc.biome.value,
            sc.major_feature.value,
            c.q, c.r, has_ww,
        )

    # 7. Pre-compute fast-travel costs
    ft_costs = compute_fast_travel_costs(cells)

    return HexFlower(
        parent_coord=parent.coord,
        cells=cells,
        edges=edge_segments,
        feature_cell=feature_cell,
        fast_travel_costs=ft_costs,
    )


def generate_flowers(
    cells: dict[HexCoord, HexCell],
    world_seed: int,
) -> None:
    """Generate flowers for all macro hex cells in place.

    Each cell gets a deterministic seed derived from the world
    seed and cell coordinates.
    """
    for coord, cell in cells.items():
        cell_seed = hash((world_seed, coord.q, coord.r)) & 0x7FFFFFFF
        cell.flower = generate_flower(cell, cells, cell_seed)


# ---------------------------------------------------------------------------
# Starting position for new hex games
# ---------------------------------------------------------------------------


def entry_sub_hex_for_edge(edge: int | None) -> HexCoord:
    """Pick the ring-2 sub-hex the player enters from.

    *edge* is the NEIGHBOR_OFFSETS direction the player was
    traveling when they entered this hex. The entry sub-hex is
    on the opposite side of the flower (they came from that
    direction, so they enter at the boundary facing back).

    Returns ``HexCoord(0, 0)`` (center) if edge is None.
    """
    if edge is None:
        return HexCoord(0, 0)
    opposite = (edge + 3) % 6
    # Pick the vertex hex (second element of the pair)
    return EDGE_TO_RING2[opposite][1]


def pick_flower_start(
    hw: "HexWorld",
    difficulty: "Difficulty",
    seed: int,
) -> tuple[HexCoord, HexCoord]:
    """Pick the starting (macro_hex, sub_hex) for a new hex game.

    * Easy/Medium: a hex adjacent to the hub. The sub-hex is a
      ring-2 cell on the edge facing the hub.
    * Survival: a random non-feature hex, random sub-hex.

    Returns ``(macro_coord, sub_hex_coord)``.
    """
    from nhc.hexcrawl.model import HexWorld
    from nhc.hexcrawl.mode import Difficulty

    rng = random.Random(seed)
    hub = hw.last_hub

    if difficulty is not Difficulty.SURVIVAL:
        assert hub is not None
        # Start at the hub hex, center of the flower
        return (hub, HexCoord(0, 0))

    # Survival: random non-feature hex
    candidates = [
        c for c, cell in hw.cells.items()
        if cell.feature is HexFeatureType.NONE
        and c != hub
    ]
    if not candidates:
        raise RuntimeError(
            "no non-feature hex available for survival start"
        )
    macro = rng.choice(candidates)
    return (macro, HexCoord(0, 0))

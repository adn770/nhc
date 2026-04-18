"""Feature placement helpers shared by every hex world generator.

Given a biome map (``hexes_by_biome: dict[Biome,
list[HexCoord]]``) plus the pack's feature targets, stamp a
hub / villages / dungeons / wonders onto a mutable cell dict.
Both :func:`nhc.hexcrawl.generator.generate_test_world` (BSP)
and :func:`nhc.hexcrawl.generator.generate_perlin_world` (noise)
call into here after their own biome-assignment step, so the
feature contract stays identical.

Extracted in M-G.2 from ``generator._attempt``; behaviour
unchanged, just organised.
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord, neighbors
from nhc.hexcrawl.model import (
    Biome,
    DungeonRef,
    HexCell,
    HexFeatureType,
)
from nhc.hexcrawl.pack import PackMeta
from nhc.hexcrawl.patterns import PATTERNS, place_pattern


# Default pattern set. B2 (pack YAML schema) will let packs
# override this per-world; until then every generated world
# attempts the Caves-of-Chaos placement.
DEFAULT_ENABLED_PATTERNS: list[str] = ["caves_of_chaos"]


# Settlement features — these must not be placed adjacent to
# each other so the map reads as distinct communities with
# wilderness between them rather than an urban sprawl.
_SETTLEMENT_FEATURES: frozenset[HexFeatureType] = frozenset({
    HexFeatureType.CITY,
    HexFeatureType.VILLAGE,
})


def assign_cave_clusters(
    cells: dict[HexCoord, HexCell],
) -> dict[HexCoord, list[HexCoord]]:
    """BFS over CAVE hexes to group adjacent ones into clusters.

    Returns ``{canonical_coord: [member_coords, ...]}``.  The
    canonical coord is the smallest ``(q, r)`` in the cluster
    (sorted lexicographically). Each cave's
    :attr:`DungeonRef.cluster_id` is updated in place, and
    ``DungeonRef.depth`` is set to 2 (all caves are two-floor).
    Solo caves form a cluster of size 1.
    """
    cave_coords = {
        c for c, cell in cells.items()
        if cell.feature is HexFeatureType.CAVE
        and cell.dungeon is not None
    }
    visited: set[HexCoord] = set()
    clusters: dict[HexCoord, list[HexCoord]] = {}

    for start in sorted(cave_coords, key=lambda c: (c.q, c.r)):
        if start in visited:
            continue
        # BFS to find the connected component.
        component: list[HexCoord] = []
        frontier = [start]
        while frontier:
            cur = frontier.pop()
            if cur in visited:
                continue
            visited.add(cur)
            component.append(cur)
            for n in neighbors(cur):
                if n in cave_coords and n not in visited:
                    frontier.append(n)
        component.sort(key=lambda c: (c.q, c.r))
        canonical = component[0]
        clusters[canonical] = component
        # Tag each cave with its cluster + two-floor depth.
        for c in component:
            cell = cells[c]
            cell.dungeon.cluster_id = canonical
            cell.dungeon.depth = 2

    return clusters


class FeaturePlacementError(Exception):
    """Signal that the current biome roll cannot host the required
    feature counts. Callers catch this and retry with a fresh
    biome map / seed."""


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------


def _adjacent_to_settlement(
    coord: HexCoord,
    cells: dict[HexCoord, HexCell],
) -> bool:
    """True if any neighbour of ``coord`` is a settlement hex."""
    for n in neighbors(coord):
        cell = cells.get(n)
        if cell is not None and cell.feature in _SETTLEMENT_FEATURES:
            return True
    return False


def _near_river(
    coord: HexCoord,
    cells: dict[HexCoord, HexCell],
) -> bool:
    """True if *coord* or any of its neighbours has a river segment."""
    cell = cells.get(coord)
    if cell is not None and any(s.type == "river" for s in cell.edges):
        return True
    for n in neighbors(coord):
        ncell = cells.get(n)
        if ncell is not None and any(
            s.type == "river" for s in ncell.edges
        ):
            return True
    return False


# Village-tier size weighting. Hamlet is the rustic default,
# village is the common case, town is rarer and larger. The
# hub is always "city" — that's the capital of the map.
_VILLAGE_SIZE_WEIGHTS: list[tuple[str, float]] = [
    ("hamlet", 0.35),
    ("village", 0.50),
    ("town", 0.15),
]


def _pick_village_size_class(rng: random.Random) -> str:
    """Choose a size class for a non-hub settlement."""
    names = [n for n, _ in _VILLAGE_SIZE_WEIGHTS]
    weights = [w for _, w in _VILLAGE_SIZE_WEIGHTS]
    return rng.choices(names, weights=weights, k=1)[0]


def _place_patterns(
    cells: dict[HexCoord, HexCell],
    taken: set[HexCoord],
    rng: random.Random,
    enabled_patterns: list[str] | None = None,
) -> int:
    """Stamp enabled feature patterns onto the cell map.

    Returns the number of hexes consumed by pattern placements
    (anchor + satellites). Callers subtract this from the dungeon
    budget so patterns don't double-count against the pack's
    generic dungeon target.
    """
    if enabled_patterns is None:
        enabled_patterns = DEFAULT_ENABLED_PATTERNS

    consumed = 0
    for pattern_name in enabled_patterns:
        pattern = PATTERNS.get(pattern_name)
        if pattern is None:
            continue
        before = len(taken)
        if place_pattern(pattern, cells, taken, rng):
            consumed += len(taken) - before
    return consumed


def pick_hub(
    hexes_by_biome: dict[Biome, list[HexCoord]],
    rng: random.Random,
    cells: dict[HexCoord, HexCell] | None = None,
) -> HexCoord | None:
    """Pick a greenlands hex for the hub; fall back to drylands.

    When *cells* is provided and contains rivers, the hub
    prefers hexes within distance 1 of a river hex. Falls back
    to a random candidate if no river-adjacent hex exists.
    """
    pool = list(hexes_by_biome.get(Biome.GREENLANDS, []))
    if not pool:
        pool = list(hexes_by_biome.get(Biome.DRYLANDS, []))
    if not pool:
        return None
    # Soft river-proximity preference.
    if cells is not None:
        river_adj = [c for c in pool if _near_river(c, cells)]
        if river_adj:
            return rng.choice(river_adj)
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# Dungeons
# ---------------------------------------------------------------------------


def _template_for(feature: HexFeatureType) -> str:
    return {
        HexFeatureType.CAVE: "procedural:cave",
        HexFeatureType.RUIN: "procedural:ruin",
        HexFeatureType.TOWER: "procedural:tower",
        HexFeatureType.GRAVEYARD: "procedural:crypt",
        HexFeatureType.KEEP: "procedural:keep",
    }.get(feature, "procedural:cave")


def place_dungeons(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    taken: set[HexCoord],
    n: int,
    rng: random.Random,
) -> None:
    """Place ``n`` dungeon features.

    Prefers variety: first place 1 cave (mountain), 1 ruin (forest
    or deadlands), 1 tower (any biome), then fill the rest as
    towers / extra caves / ruins depending on biome availability.
    """
    if n == 0:
        return

    def _pool(biomes: tuple[Biome, ...]) -> list[HexCoord]:
        out: list[HexCoord] = []
        for b in biomes:
            out.extend(c for c in hexes_by_biome[b] if c not in taken)
        return out

    placed = 0

    recipes: list[tuple[HexFeatureType, tuple[Biome, ...]]] = [
        (HexFeatureType.CAVE, (Biome.MOUNTAIN,)),
        (HexFeatureType.RUIN, (Biome.FOREST, Biome.DEADLANDS)),
        (HexFeatureType.GRAVEYARD, (Biome.DEADLANDS, Biome.ICELANDS,
                                    Biome.SWAMP, Biome.MARSH)),
        (HexFeatureType.KEEP, (Biome.GREENLANDS, Biome.HILLS,
                               Biome.DRYLANDS)),
        (HexFeatureType.TOWER, tuple(
            b for b in Biome if b is not Biome.WATER
        )),
    ]
    # First: one of each type if possible.
    for feature, biomes in recipes:
        if placed >= n:
            break
        pool = _pool(biomes)
        if not pool:
            continue
        c = rng.choice(pool)
        cells[c].feature = feature
        cells[c].dungeon = DungeonRef(template=_template_for(feature))
        taken.add(c)
        placed += 1

    # Remaining: round-robin over recipes until filled or exhausted.
    while placed < n:
        made_progress = False
        for feature, biomes in recipes:
            if placed >= n:
                break
            pool = _pool(biomes)
            if not pool:
                continue
            c = rng.choice(pool)
            cells[c].feature = feature
            cells[c].dungeon = DungeonRef(template=_template_for(feature))
            taken.add(c)
            placed += 1
            made_progress = True
        if not made_progress:
            raise FeaturePlacementError(
                f"could not place {n} dungeons "
                f"(placed {placed} before exhausting biome pools)"
            )


# ---------------------------------------------------------------------------
# Top-level feature pass (hub + villages + dungeons + wonders)
# ---------------------------------------------------------------------------


def place_features(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    pack: PackMeta,
    rng: random.Random,
) -> HexCoord:
    """Stamp the pack's feature targets onto ``cells``.

    Order is deliberate:

    1. Hub (greenlands or drylands; name + desc keys + settlement
       template).
    2. Villages (from the leftover greenlands / drylands pool).
    3. Dungeons (biome-themed: caves in mountain, ruins in forest
       or deadlands, towers anywhere).
    4. Wonders (icelands / deadlands hexes; random wonder sub-type).

    Returns the hub coord so the caller can stash it on
    ``HexWorld.last_hub``.
    """
    hub = pick_hub(hexes_by_biome, rng, cells)
    if hub is None:
        raise FeaturePlacementError(
            "no greenlands / drylands hex for hub",
        )
    cells[hub].feature = HexFeatureType.CITY
    cells[hub].name_key = "content.testland.hex.hub.name"
    cells[hub].desc_key = "content.testland.hex.hub.description"
    # Placeholder so enter_hex_feature can land on a generated
    # town floor; actual town-map generation is M-2.1 work.
    cells[hub].dungeon = DungeonRef(
        template="procedural:settlement", size_class="city",
    )
    taken: set[HexCoord] = {hub}

    # Villages — placed one at a time with an adjacency check so
    # no two settlements (hub + villages) end up next to each
    # other. The map should read as distinct communities with
    # wilderness between them.
    vt = pack.features.village
    n_villages = rng.randint(vt.min, vt.max)
    village_pool = [
        c for c in (
            hexes_by_biome[Biome.GREENLANDS]
            + hexes_by_biome[Biome.DRYLANDS]
        ) if c not in taken
    ]
    rng.shuffle(village_pool)
    # Soft river-proximity preference: river-adjacent candidates
    # appear first in the pool so they are tried before distant ones.
    village_pool.sort(
        key=lambda c: (0 if _near_river(c, cells) else 1),
    )
    placed_villages = 0
    for c in village_pool:
        if placed_villages >= n_villages:
            break
        # Reject candidates adjacent to any existing settlement.
        if _adjacent_to_settlement(c, cells):
            continue
        cells[c].feature = HexFeatureType.VILLAGE
        cells[c].dungeon = DungeonRef(
            template="procedural:settlement",
            size_class=_pick_village_size_class(rng),
        )
        taken.add(c)
        placed_villages += 1
    if placed_villages < vt.min:
        raise FeaturePlacementError(
            f"could only place {placed_villages} villages "
            f"(need at least {vt.min}; settlement spacing "
            f"rejected too many candidates)",
        )

    # Feature patterns (e.g., Caves of Chaos keep + lair cluster).
    # Patterns run before generic dungeon placement and consume
    # from the same dungeon budget so a pack's feature count
    # stays meaningful.
    pattern_consumed = _place_patterns(cells, taken, rng)

    # Dungeons.
    dt = pack.features.dungeon
    n_dungeons = rng.randint(dt.min, dt.max)
    remaining = max(0, n_dungeons - pattern_consumed)
    if remaining > 0:
        place_dungeons(
            cells, hexes_by_biome, taken, remaining, rng,
        )

    # Wonders.
    wt = pack.features.wonder
    n_wonders = rng.randint(wt.min, wt.max)
    wonder_pool = [
        c for c in (
            hexes_by_biome[Biome.ICELANDS]
            + hexes_by_biome[Biome.DEADLANDS]
        ) if c not in taken
    ]
    if len(wonder_pool) < n_wonders:
        raise FeaturePlacementError(
            f"not enough icelands/deadlands hexes for "
            f"{n_wonders} wonders",
        )
    wonder_types = [
        HexFeatureType.WONDER, HexFeatureType.CRYSTALS,
        HexFeatureType.STONES, HexFeatureType.PORTAL,
    ]
    for c in rng.sample(wonder_pool, n_wonders):
        cells[c].feature = rng.choice(wonder_types)
        taken.add(c)

    # Cave cluster detection — groups adjacent CAVE hexes so they
    # share a connected Floor 2 underground. Must run after all
    # features are placed so every cave is visible. Returns the
    # clusters dict for the caller to store on HexWorld.
    clusters = assign_cave_clusters(cells)

    return hub, clusters

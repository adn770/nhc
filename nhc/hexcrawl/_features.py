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
    HexFeatureType.COMMUNITY,
})


# Biome eligibility matrix (design/biome_features.md §3). Single
# source of truth for which hex biomes can host which major
# feature. Consulted by both ``place_features`` (hub / village /
# community / ruin) and ``place_dungeons`` (MANSION / COTTAGE /
# TEMPLE / etc.). Features not listed here retain their ad-hoc
# biome pools inside ``place_dungeons`` (CAVE, GRAVEYARD, TOWER).
FEATURE_BIOMES: dict[HexFeatureType, tuple[Biome, ...]] = {
    HexFeatureType.CITY: (Biome.GREENLANDS, Biome.HILLS),
    HexFeatureType.VILLAGE: (
        Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
        Biome.DRYLANDS, Biome.MARSH, Biome.MOUNTAIN,
    ),
    HexFeatureType.COMMUNITY: (
        Biome.GREENLANDS, Biome.HILLS, Biome.SANDLANDS,
        Biome.DRYLANDS, Biome.MARSH, Biome.MOUNTAIN,
        Biome.FOREST,
    ),
    HexFeatureType.FARM: (Biome.GREENLANDS,),
    HexFeatureType.MANSION: (
        Biome.GREENLANDS, Biome.HILLS, Biome.MARSH,
    ),
    HexFeatureType.COTTAGE: (Biome.FOREST,),
    HexFeatureType.TEMPLE: (
        Biome.MOUNTAIN, Biome.FOREST,
        Biome.SANDLANDS, Biome.ICELANDS,
    ),
    HexFeatureType.RUIN: (
        Biome.FOREST, Biome.DEADLANDS,
        Biome.MARSH, Biome.SANDLANDS, Biome.ICELANDS,
    ),
    HexFeatureType.KEEP: (
        Biome.GREENLANDS, Biome.HILLS, Biome.DRYLANDS,
    ),
}


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
    """Pick a hub hex from the CITY biome pool.

    Greenlands is the preferred biome; hills is the sole
    fallback because CITY is restricted to those two biomes in
    :data:`FEATURE_BIOMES`. When *cells* is provided and contains
    rivers, the hub prefers hexes within distance 1 of a river
    hex; otherwise it falls back to a random candidate.
    """
    pool = list(hexes_by_biome.get(Biome.GREENLANDS, []))
    if not pool:
        pool = list(hexes_by_biome.get(Biome.HILLS, []))
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
        # Keep hexes now route through the keep site assembler
        # (see site_kind mapping below); the template string is
        # only used for seeding, so a neutral placeholder keeps
        # the dungeon_seed hash stable across world generations.
        HexFeatureType.KEEP: "site:keep",
        # Communities route through the town assembler as
        # hamlets; the template string matches VILLAGE / CITY.
        HexFeatureType.COMMUNITY: "procedural:settlement",
        HexFeatureType.TEMPLE: "site:temple",
        HexFeatureType.COTTAGE: "site:cottage",
    }.get(feature, "procedural:cave")


def _site_kind_for(feature: HexFeatureType) -> str | None:
    """Map a hex feature to a building-generator site kind.

    Returns one of the SITE_KINDS strings when the feature should
    be generated by the building-generator subsystem, or ``None``
    for dungeons and caves that still use the template-based
    pipeline.
    """
    return {
        HexFeatureType.TOWER: "tower",
        HexFeatureType.KEEP: "keep",
        HexFeatureType.MANSION: "mansion",
        HexFeatureType.FARM: "farm",
        HexFeatureType.CITY: "town",
        HexFeatureType.VILLAGE: "town",
        HexFeatureType.COMMUNITY: "town",
        HexFeatureType.TEMPLE: "temple",
        HexFeatureType.COTTAGE: "cottage",
        HexFeatureType.RUIN: "ruin",
    }.get(feature)


def place_dungeons(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    taken: set[HexCoord],
    n: int,
    rng: random.Random,
) -> None:
    """Place ``n`` dungeon features.

    Prefers variety: first place one of each feature kind, then
    round-robins the remaining budget over the same recipes.
    Pools come from :data:`FEATURE_BIOMES` for site-assembler
    features (COTTAGE, TEMPLE, KEEP, MANSION, FARM); CAVE /
    GRAVEYARD / TOWER keep bespoke pools. RUIN placement has
    moved to the dedicated ruin loop in :func:`place_features`.
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
        (HexFeatureType.GRAVEYARD, (Biome.DEADLANDS, Biome.ICELANDS,
                                    Biome.SWAMP, Biome.MARSH)),
        (HexFeatureType.KEEP, FEATURE_BIOMES[HexFeatureType.KEEP]),
        (HexFeatureType.MANSION,
         FEATURE_BIOMES[HexFeatureType.MANSION]),
        (HexFeatureType.FARM, FEATURE_BIOMES[HexFeatureType.FARM]),
        (HexFeatureType.COTTAGE,
         FEATURE_BIOMES[HexFeatureType.COTTAGE]),
        (HexFeatureType.TEMPLE,
         FEATURE_BIOMES[HexFeatureType.TEMPLE]),
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
        cells[c].dungeon = DungeonRef(
            template=_template_for(feature),
            site_kind=_site_kind_for(feature),
        )
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
            cells[c].dungeon = DungeonRef(
            template=_template_for(feature),
            site_kind=_site_kind_for(feature),
        )
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


def _place_settlement_loop(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    taken: set[HexCoord],
    feature: HexFeatureType,
    size_class: str,
    count: int,
    rng: random.Random,
    min_required: int = 0,
) -> int:
    """Place up to ``count`` settlements of ``feature``.

    Consults :data:`FEATURE_BIOMES` for the biome pool, rejects
    candidates adjacent to an existing settlement, and pins
    ``size_class`` on the DungeonRef. Raises
    :class:`FeaturePlacementError` when fewer than
    ``min_required`` placements are possible.
    """
    if count <= 0:
        return 0
    pool = [
        c for b in FEATURE_BIOMES[feature]
        for c in hexes_by_biome[b] if c not in taken
    ]
    rng.shuffle(pool)
    # Soft river-proximity preference for settlement placement.
    pool.sort(key=lambda c: (0 if _near_river(c, cells) else 1))
    placed = 0
    for c in pool:
        if placed >= count:
            break
        if _adjacent_to_settlement(c, cells):
            continue
        cells[c].feature = feature
        cells[c].dungeon = DungeonRef(
            template="procedural:settlement",
            size_class=size_class,
            site_kind="town",
        )
        taken.add(c)
        placed += 1
    if placed < min_required:
        raise FeaturePlacementError(
            f"could only place {placed} {feature.value} hexes "
            f"(need at least {min_required}; settlement spacing "
            f"rejected too many candidates)",
        )
    return placed


def _place_ruins(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    taken: set[HexCoord],
    count: int,
    rng: random.Random,
) -> int:
    """Place ``count`` RUIN hexes from the biome pool.

    Ruins are abandoned dungeon entrances, not settlements, so
    they are free to sit adjacent to other features.
    """
    if count <= 0:
        return 0
    pool = [
        c for b in FEATURE_BIOMES[HexFeatureType.RUIN]
        for c in hexes_by_biome[b] if c not in taken
    ]
    if len(pool) < count:
        raise FeaturePlacementError(
            f"not enough ruin-eligible hexes to place {count} "
            f"ruins (have {len(pool)})",
        )
    for c in rng.sample(pool, count):
        cells[c].feature = HexFeatureType.RUIN
        cells[c].dungeon = DungeonRef(
            template=_template_for(HexFeatureType.RUIN),
            site_kind=_site_kind_for(HexFeatureType.RUIN),
        )
        taken.add(c)
    return count


def place_features(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    pack: PackMeta,
    rng: random.Random,
) -> HexCoord:
    """Stamp the pack's feature targets onto ``cells``.

    Order is deliberate:

    1. Hub (CITY biome pool from :data:`FEATURE_BIOMES`).
    2. Villages — pinned to ``size_class="village"``.
    3. Communities — pinned to ``size_class="hamlet"``.
    4. Ruins — dedicated pool from ``pack.features.ruin``.
    5. Feature patterns (Caves of Chaos, etc.).
    6. Generic dungeons (caves, towers, keeps, mansions, …).
    7. Wonders.

    Returns ``(hub_coord, cave_clusters)`` so the caller can
    stash the hub on ``HexWorld.last_hub``.
    """
    hub = pick_hub(hexes_by_biome, rng, cells)
    if hub is None:
        raise FeaturePlacementError(
            "no greenlands / hills hex for hub",
        )
    cells[hub].feature = HexFeatureType.CITY
    cells[hub].name_key = "content.testland.hex.hub.name"
    cells[hub].desc_key = "content.testland.hex.hub.description"
    cells[hub].dungeon = DungeonRef(
        template="procedural:settlement", size_class="city",
        site_kind="town",
    )
    taken: set[HexCoord] = {hub}

    # Villages — size_class is pinned; no random hamlet / town roll.
    vt = pack.features.village
    n_villages = rng.randint(vt.min, vt.max)
    _place_settlement_loop(
        cells, hexes_by_biome, taken,
        feature=HexFeatureType.VILLAGE,
        size_class="village",
        count=n_villages,
        rng=rng,
        min_required=vt.min,
    )

    # Communities — hamlet-scale settlements, own biome pool
    # (includes FOREST), respect settlement spacing.
    ct = pack.features.community
    n_communities = rng.randint(ct.min, ct.max)
    _place_settlement_loop(
        cells, hexes_by_biome, taken,
        feature=HexFeatureType.COMMUNITY,
        size_class="hamlet",
        count=n_communities,
        rng=rng,
        min_required=ct.min,
    )

    # Ruins — abandoned dungeon entrances with their own pack knob.
    rt = pack.features.ruin
    n_ruins = rng.randint(rt.min, rt.max)
    _place_ruins(cells, hexes_by_biome, taken, n_ruins, rng)

    # Feature patterns (e.g., Caves of Chaos keep + lair cluster).
    # Patterns run before generic dungeon placement and consume
    # from the same dungeon budget so a pack's feature count
    # stays meaningful.
    pattern_consumed = _place_patterns(
        cells, taken, rng,
        enabled_patterns=list(pack.features.patterns),
    )

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

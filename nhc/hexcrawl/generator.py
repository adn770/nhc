"""BSP region partitioning generator for the test setting.

Produces a :class:`HexWorld` populated with biome regions and hex
features. The algorithm:

1. Recursively split the axial (width, height) rectangle into N
   roughly-equal rectangular regions, each within [min_cells,
   max_cells] cells.
2. Assign one biome per region from a curated pool that guarantees
   at least one GREENLANDS (hub), one MOUNTAIN (caves), one FOREST
   (ruins), and one ICELANDS (wonders).
3. Place the hub in a greenlands region.
4. Scatter villages across greenlands/drylands hexes.
5. Scatter dungeon features by biome rule: caves in mountain, ruins
   in forest or deadlands, towers anywhere.
6. Scatter wonder-type features across icelands / deadlands hexes.

Reachability is guaranteed by construction -- an axial rectangle is
fully connected via hex adjacency. The retry loop exists to handle
feature targets that cannot fit in the current partition (e.g., the
test setting asks for 5 caves but this roll produced only 4 mountain
hexes).
"""

from __future__ import annotations

import random

from nhc.hexcrawl.coords import HexCoord
from nhc.hexcrawl.model import (
    Biome,
    HexCell,
    HexFeatureType,
    HexWorld,
)
from nhc.hexcrawl.pack import PackMeta


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GeneratorRetryError(RuntimeError):
    """Raised after exhausting retry attempts."""


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


# Rectangular BSP region: (q_min, r_min, q_max_exclusive, r_max_exclusive).
Rect = tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# BSP partitioning
# ---------------------------------------------------------------------------


def _area(rect: Rect) -> int:
    q_min, r_min, q_max, r_max = rect
    return (q_max - q_min) * (r_max - r_min)


def _partition(
    width: int,
    height: int,
    target_regions: int,
    min_cells: int,
    max_cells: int,
    rng: random.Random,
) -> list[Rect]:
    """Recursively split a (width x height) rectangle.

    Splits continue until the partition holds ``target_regions``
    regions AND every region has area in [min_cells, max_cells].
    A region that cannot be split without violating ``min_cells``
    on either side is left as-is, even if it exceeds ``max_cells``;
    the feature-placement step will cope with outsize regions.
    """

    regions: list[Rect] = [(0, 0, width, height)]

    def try_split(rect: Rect) -> tuple[Rect, Rect] | None:
        q_min, r_min, q_max, r_max = rect
        w = q_max - q_min
        h = r_max - r_min
        # Try the longer axis first, fall back to the shorter.
        axes = ("q", "r") if w >= h else ("r", "q")
        for axis in axes:
            if axis == "q" and w > 1:
                picks = list(range(q_min + 1, q_max))
                rng.shuffle(picks)
                for split in picks:
                    a = (q_min, r_min, split, r_max)
                    b = (split, r_min, q_max, r_max)
                    if _area(a) >= min_cells and _area(b) >= min_cells:
                        return a, b
            if axis == "r" and h > 1:
                picks = list(range(r_min + 1, r_max))
                rng.shuffle(picks)
                for split in picks:
                    a = (q_min, r_min, q_max, split)
                    b = (q_min, split, q_max, r_max)
                    if _area(a) >= min_cells and _area(b) >= min_cells:
                        return a, b
        return None

    def _work_left() -> bool:
        return (
            len(regions) < target_regions
            or any(_area(r) > max_cells for r in regions)
        )

    while _work_left():
        # Prefer splitting the largest region.
        order = sorted(
            range(len(regions)),
            key=lambda i: _area(regions[i]),
            reverse=True,
        )
        did_split = False
        for i in order:
            split = try_split(regions[i])
            if split is not None:
                a, b = split
                regions[i:i + 1] = [a, b]
                did_split = True
                break
        if not did_split:
            break

    return regions


# ---------------------------------------------------------------------------
# Biome assignment
# ---------------------------------------------------------------------------


_ESSENTIAL_BIOMES: tuple[Biome, ...] = (
    Biome.GREENLANDS,       # hub
    Biome.MOUNTAIN,         # caves
    Biome.FOREST,           # ruins
    Biome.ICELANDS,         # wonders
)

_FILL_BIOMES: tuple[Biome, ...] = (
    Biome.DRYLANDS,
    Biome.DEADLANDS,
    Biome.SANDLANDS,
)


def _assign_biomes(
    regions: list[Rect], rng: random.Random,
) -> dict[int, Biome]:
    """Map region index -> biome.

    Guarantees each essential biome is present if the number of
    regions allows it (>=4 regions => all four). Remaining slots are
    filled from the variety pool.
    """
    n = len(regions)
    pool = list(_ESSENTIAL_BIOMES[:n])
    fill = list(_FILL_BIOMES)
    while len(pool) < n:
        pool.append(rng.choice(fill))
    rng.shuffle(pool)
    return {i: pool[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Top-level generation
# ---------------------------------------------------------------------------


def generate_test_world(
    seed: int,
    pack: PackMeta,
    max_attempts: int = 10,
) -> HexWorld:
    """Generate a :class:`HexWorld` for the test setting.

    Retries up to ``max_attempts`` times if feature placement can't
    meet the pack's targets with the current partition / biome roll.
    """
    rng = random.Random(seed)
    last_err: str | None = None
    for _ in range(max_attempts):
        try:
            return _attempt(rng, pack)
        except _FeaturePlacementError as exc:
            last_err = str(exc)
    raise GeneratorRetryError(
        f"exhausted {max_attempts} attempts; last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# Attempt: partition, biomes, features
# ---------------------------------------------------------------------------


class _FeaturePlacementError(Exception):
    """Internal signal that the current attempt cannot host the
    required features; caught by the retry loop."""


def _attempt(rng: random.Random, pack: PackMeta) -> HexWorld:
    mp = pack.map

    regions = _partition(
        width=mp.width,
        height=mp.height,
        target_regions=mp.num_regions,
        min_cells=mp.region_min,
        max_cells=mp.region_max,
        rng=rng,
    )
    biomes = _assign_biomes(regions, rng)

    # Build per-cell biome mapping from region rectangles.
    cells: dict[HexCoord, HexCell] = {}
    hexes_by_biome: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
    for i, (q_min, r_min, q_max, r_max) in enumerate(regions):
        biome = biomes[i]
        for q in range(q_min, q_max):
            for r in range(r_min, r_max):
                c = HexCoord(q, r)
                cells[c] = HexCell(coord=c, biome=biome)
                hexes_by_biome[biome].append(c)

    # -- Hub ------------------------------------------------------
    hub = _pick_hub(hexes_by_biome, rng)
    if hub is None:
        raise _FeaturePlacementError("no greenlands / drylands hex for hub")
    cells[hub].feature = HexFeatureType.CITY
    cells[hub].name_key = "content.testland.hex.hub.name"

    taken: set[HexCoord] = {hub}

    # -- Villages -------------------------------------------------
    vt = pack.features.village
    n_villages = rng.randint(vt.min, vt.max)
    village_pool = [
        c for c in (
            hexes_by_biome[Biome.GREENLANDS]
            + hexes_by_biome[Biome.DRYLANDS]
        ) if c not in taken
    ]
    if len(village_pool) < n_villages:
        raise _FeaturePlacementError(
            f"not enough greenlands/drylands hexes for {n_villages} villages"
        )
    for c in rng.sample(village_pool, n_villages):
        cells[c].feature = HexFeatureType.VILLAGE
        taken.add(c)

    # -- Dungeons -------------------------------------------------
    dt = pack.features.dungeon
    n_dungeons = rng.randint(dt.min, dt.max)
    _place_dungeons(cells, hexes_by_biome, taken, n_dungeons, rng)

    # -- Wonders --------------------------------------------------
    wt = pack.features.wonder
    n_wonders = rng.randint(wt.min, wt.max)
    wonder_pool = [
        c for c in (
            hexes_by_biome[Biome.ICELANDS]
            + hexes_by_biome[Biome.DEADLANDS]
        ) if c not in taken
    ]
    if len(wonder_pool) < n_wonders:
        raise _FeaturePlacementError(
            f"not enough icelands/deadlands hexes for {n_wonders} wonders"
        )
    wonder_types = [
        HexFeatureType.WONDER, HexFeatureType.CRYSTALS,
        HexFeatureType.STONES, HexFeatureType.PORTAL,
    ]
    for c in rng.sample(wonder_pool, n_wonders):
        cells[c].feature = rng.choice(wonder_types)
        taken.add(c)

    # -- Build the world ------------------------------------------
    world = HexWorld(
        pack_id=pack.id,
        seed=rng.randrange(1 << 30),      # downstream RNG seeding
        width=mp.width,
        height=mp.height,
        biome_costs=dict(pack.biome_costs),
    )
    for cell in cells.values():
        world.set_cell(cell)
    world.last_hub = hub
    return world


# ---------------------------------------------------------------------------
# Feature placement helpers
# ---------------------------------------------------------------------------


def _pick_hub(
    hexes_by_biome: dict[Biome, list[HexCoord]],
    rng: random.Random,
) -> HexCoord | None:
    greens = list(hexes_by_biome.get(Biome.GREENLANDS, []))
    if greens:
        return rng.choice(greens)
    drys = list(hexes_by_biome.get(Biome.DRYLANDS, []))
    if drys:
        return rng.choice(drys)
    return None


def _place_dungeons(
    cells: dict[HexCoord, HexCell],
    hexes_by_biome: dict[Biome, list[HexCoord]],
    taken: set[HexCoord],
    n: int,
    rng: random.Random,
) -> None:
    """Place ``n`` dungeon features.

    Prefers variety: first place 1 cave (mountain), 1 ruin (forest
    or deadlands), 1 tower (any biome), then fill the rest as towers
    or extra caves/ruins depending on biome availability.
    """
    if n == 0:
        return

    def _pool(biomes: tuple[Biome, ...]) -> list[HexCoord]:
        out: list[HexCoord] = []
        for b in biomes:
            out.extend(c for c in hexes_by_biome[b] if c not in taken)
        return out

    placed = 0
    # First: one of each type if possible.
    recipes: list[tuple[HexFeatureType, tuple[Biome, ...]]] = [
        (HexFeatureType.CAVE, (Biome.MOUNTAIN,)),
        (HexFeatureType.RUIN, (Biome.FOREST, Biome.DEADLANDS)),
        (HexFeatureType.TOWER, tuple(Biome)),
    ]
    for feature, biomes in recipes:
        if placed >= n:
            break
        pool = _pool(biomes)
        if not pool:
            continue
        c = rng.choice(pool)
        cells[c].feature = feature
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
            taken.add(c)
            placed += 1
            made_progress = True
        if not made_progress:
            raise _FeaturePlacementError(
                f"could not place {n} dungeons "
                f"(placed {placed} before exhausting biome pools)"
            )

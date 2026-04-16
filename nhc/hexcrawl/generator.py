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
from nhc.hexcrawl.model import Biome, HexCell, HexWorld
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


# Shape helpers live in nhc.hexcrawl.coords now (M-G.2 refactor).
# Re-exported here under the original names so the test-suite
# imports (and any external code) keep working without churn.
from nhc.hexcrawl.coords import (
    expected_shape_cell_count,  # noqa: F401
    shape_r_range as _shape_r_range,  # noqa: F401
    valid_shape_hex as _valid_shape_hex,
)


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
    regions: list[Rect],
    valid_cells_per_region: list[int],
    rng: random.Random,
) -> dict[int, Biome]:
    """Map region index -> biome.

    Guarantees each essential biome lands in a region that
    actually holds valid cells. Under staggered layouts some
    partitions can end up mostly / entirely in the "invalid"
    corners of the axial bounding box; if we let an essential
    biome fall there, the generated world is missing that biome
    entirely.

    We sort region indices by their valid-cell count (desc),
    assign essentials to the top slots, fills to the remainder,
    then shuffle within each group so the biome layout still
    varies seed-to-seed.
    """
    n = len(regions)
    # Biomes pool: essentials first (up to n), then fills until n.
    essentials = list(_ESSENTIAL_BIOMES[:n])
    fill_pool = list(_FILL_BIOMES)
    fills: list[Biome] = []
    while len(essentials) + len(fills) < n:
        fills.append(rng.choice(fill_pool))
    rng.shuffle(essentials)
    rng.shuffle(fills)
    # Rank regions by valid-cell count, descending (so the biggest
    # "real" regions host essentials).
    ranked = sorted(
        range(n), key=lambda i: valid_cells_per_region[i], reverse=True,
    )
    assignment: dict[int, Biome] = {}
    for slot, region_idx in enumerate(ranked):
        if slot < len(essentials):
            assignment[region_idx] = essentials[slot]
        else:
            assignment[region_idx] = fills[slot - len(essentials)]
    return assignment


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


# Back-compat alias: a handful of earlier tests and callers
# imported the private name from this module. The exception body
# now lives alongside the feature placer.
from nhc.hexcrawl._features import (  # noqa: E402
    FeaturePlacementError as _FeaturePlacementError,
    place_features as _place_features,
)


def _attempt(rng: random.Random, pack: PackMeta) -> HexWorld:
    mp = pack.map

    # Rectangular odd-q staggered layout: columns alternate between
    # ``height`` and ``height - 1`` hexes, and the axial r axis is
    # shifted per column so the overall silhouette is a rectangle.
    # The axial r range spans [-(width-1)//2, height). We partition
    # the full axial bounding box (width x (height + r_offset)) in
    # non-negative space and shift back when materialising cells.
    r_offset = (mp.width - 1) // 2
    axial_height = mp.height + r_offset
    regions = _partition(
        width=mp.width,
        height=axial_height,
        target_regions=mp.num_regions,
        min_cells=mp.region_min,
        max_cells=mp.region_max,
        rng=rng,
    )

    # Count valid cells per region (for biome assignment ranking).
    # Skip cells whose axial coord falls outside the rectangular
    # shape; those "ghost" cells inflate the axial-rect area but
    # never get populated.
    valid_counts: list[int] = []
    region_valid_cells: list[list[HexCoord]] = []
    for (q_min, rs_min, q_max, rs_max) in regions:
        col: list[HexCoord] = []
        for q in range(q_min, q_max):
            for rs in range(rs_min, rs_max):
                r = rs - r_offset
                if _valid_shape_hex(q, r, mp.width, mp.height):
                    col.append(HexCoord(q, r))
        region_valid_cells.append(col)
        valid_counts.append(len(col))

    biomes = _assign_biomes(regions, valid_counts, rng)

    # Build per-cell biome mapping using the pre-computed valid
    # cell lists.
    cells: dict[HexCoord, HexCell] = {}
    hexes_by_biome: dict[Biome, list[HexCoord]] = {b: [] for b in Biome}
    for i, valid_cells in enumerate(region_valid_cells):
        biome = biomes[i]
        for c in valid_cells:
            cells[c] = HexCell(coord=c, biome=biome)
            hexes_by_biome[biome].append(c)

    hub = _place_features(cells, hexes_by_biome, pack, rng)

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


# Feature placement helpers moved to nhc.hexcrawl._features
# (M-G.2). Re-exported under the original private names so any
# external caller that imports them keeps working.
from nhc.hexcrawl._features import (  # noqa: E402
    pick_hub as _pick_hub,  # noqa: F401
    place_dungeons as _place_dungeons,  # noqa: F401
)

"""Graveyard site assembler.

Stone-walled FIELD plaza with a single ``tomb_entrance`` tile and
an undead garrison sized by tier. The surface ``metadata.faction``
is pinned to ``undead`` so the encounter system also recognises the
level when something extends beyond the seeded population.

Replaces the retired ``generate_undead_site``
(see ``nhc_sites_unification_plan.md`` milestone 4e).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


# Lighter tiers lean on the less-dangerous casualties; bigger
# graveyards add ghouls and eventually wraiths.
UNDEAD_POOL_BY_TIER: dict[SiteTier, list[str]] = {
    SiteTier.SMALL: ["skeleton", "zombie"],
    SiteTier.MEDIUM: ["skeleton", "zombie", "ghoul"],
    SiteTier.LARGE: ["skeleton", "zombie", "ghoul", "wraith"],
}


UNDEAD_COUNT_BY_TIER: dict[SiteTier, int] = {
    SiteTier.SMALL: 2,
    SiteTier.MEDIUM: 3,
    SiteTier.LARGE: 5,
}


def assemble_graveyard(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType" = (
        HexFeatureType.GRAVEYARD
    ),
    tier: SiteTier = SiteTier.MEDIUM,
) -> Site:
    """Assemble a graveyard site."""
    del feature  # one shape today; kwarg kept for assembler-API parity
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_graveyard_surface(
        f"{site_id}_surface", width, height,
    )
    fx, fy = _pick_feature_tile(width, height, rng)
    tile = surface.tile_at(fx, fy)
    if tile is not None:
        tile.terrain = Terrain.FLOOR
        tile.feature = "tomb_entrance"
        tile.surface_type = SurfaceType.FIELD

    return Site(
        id=site_id,
        kind="graveyard",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def pick_undead_population(
    surface: Level,
    rng: random.Random,
    tier: SiteTier,
    *,
    exclude: set[tuple[int, int]] | None = None,
) -> list[tuple[str, tuple[int, int]]]:
    """Sample tier-scaled undead placements on FLOOR tiles.

    Skips ``exclude`` so callers can keep the entry tile and the
    tomb-entrance free of corpses. Deterministic in ``rng``.
    """
    excluded = set(exclude or ())
    floors = [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, tile in enumerate(row)
        if tile.terrain is Terrain.FLOOR and (x, y) not in excluded
    ]
    if not floors:
        return []
    rng.shuffle(floors)
    count = UNDEAD_COUNT_BY_TIER[tier]
    pool = UNDEAD_POOL_BY_TIER[tier]
    return [(rng.choice(pool), xy) for xy in floors[:count]]


def _build_graveyard_surface(
    surface_id: str, width: int, height: int,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "crypt"
    surface.metadata.prerevealed = True
    surface.metadata.faction = "undead"
    for y in range(height):
        for x in range(width):
            tile = surface.tiles[y][x]
            on_border = (
                x == 0 or y == 0
                or x == width - 1 or y == height - 1
            )
            if on_border:
                tile.terrain = Terrain.WALL
            else:
                tile.terrain = Terrain.FLOOR
                tile.surface_type = SurfaceType.FIELD
    return surface


def _pick_feature_tile(
    width: int, height: int, rng: random.Random,
) -> tuple[int, int]:
    cx, cy = width // 2, height // 2
    jx = rng.randint(-1, 1)
    jy = rng.randint(-1, 1)
    return (cx + jx, cy + jy)

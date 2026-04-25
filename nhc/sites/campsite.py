"""Campsite site assembler.

Walled FIELD clearing with a single ``campfire`` centrepiece. No
buildings, no scatter -- sit-under-the-sky shape. The dispatcher
spawns a ``campsite_traveller`` NPC adjacent to the fire.

Replaces the CAMPSITE branch of the retired
``generate_inhabited_settlement_site``
(see ``nhc_sites_unification_plan.md`` milestone 4f).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


def assemble_campsite(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType" = (
        MinorFeatureType.CAMPSITE
    ),
    tier: SiteTier = SiteTier.SMALL,
) -> Site:
    """Assemble a campsite site."""
    del feature  # one shape today; kwarg kept for assembler-API parity
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_clearing_surface(
        f"{site_id}_surface", width, height, theme="settlement",
    )
    fx, fy = _pick_feature_tile(width, height, rng)
    tile = surface.tile_at(fx, fy)
    if tile is not None:
        tile.terrain = Terrain.FLOOR
        tile.feature = "campfire"
        tile.surface_type = SurfaceType.FIELD

    return Site(
        id=site_id,
        kind="campsite",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _build_clearing_surface(
    surface_id: str, width: int, height: int, *, theme: str,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = theme
    surface.metadata.prerevealed = True
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

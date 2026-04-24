"""Clearing site assembler — natural curiosities.

Tiny sub-hex site with a single centrepiece tile on a walled
FIELD clearing. Covers MUSHROOM_RING, HERB_PATCH, HOLLOW_LOG and
BONE_PILE minor features; unknown features fall back to
``mushrooms`` to match the legacy family generator. No buildings,
no enclosure, no populator entities — the tag is the entire
interaction.

Replaces the retired ``generate_natural_curiosity_site``
(see ``nhc_sites_unification_plan.md`` milestone 4b).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.hexcrawl.sub_hex_sites import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


_CLEARING_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.MUSHROOM_RING: "mushrooms",
    MinorFeatureType.HERB_PATCH: "herbs",
    MinorFeatureType.HOLLOW_LOG: "hollow_log",
    MinorFeatureType.BONE_PILE: "bones",
}


def assemble_clearing(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType",
    tier: SiteTier = SiteTier.SMALL,
) -> Site:
    """Assemble a clearing site."""
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_clearing_surface(
        f"{site_id}_surface", width, height,
    )
    tag = _tag_for(feature)
    fx, fy = _pick_feature_tile(width, height, rng)
    tile = surface.tile_at(fx, fy)
    if tile is not None:
        tile.terrain = Terrain.FLOOR
        tile.feature = tag
        tile.surface_type = SurfaceType.FIELD

    return Site(
        id=site_id,
        kind="clearing",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _tag_for(
    feature: "HexFeatureType | MinorFeatureType",
) -> str:
    if isinstance(feature, MinorFeatureType):
        return _CLEARING_TAGS.get(feature, "mushrooms")
    return "mushrooms"


def _build_clearing_surface(
    surface_id: str, width: int, height: int,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "wilderness"
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

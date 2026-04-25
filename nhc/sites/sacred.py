"""Sacred site assembler.

Single-monument centrepiece on a walled FIELD plaza. Covers the
SHRINE / STANDING_STONE / CAIRN minor features and the
CRYSTALS / STONES / WONDER / PORTAL major features under one
shape — which is why the assembler accepts both the
``MinorFeatureType`` and ``HexFeatureType`` unions. The tile tag
keys off the feature kind so the BumpAction router still picks
the right interaction.

Replaces the retired ``generate_sacred_site``
(see ``nhc_sites_unification_plan.md`` milestone 4d).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


_SACRED_MINOR_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.SHRINE: "shrine",
    MinorFeatureType.STANDING_STONE: "monolith",
    MinorFeatureType.CAIRN: "cairn",
}

_SACRED_MAJOR_TAGS: dict[HexFeatureType, str] = {
    HexFeatureType.CRYSTALS: "crystals",
    HexFeatureType.STONES: "monolith",
    HexFeatureType.WONDER: "wonder",
    HexFeatureType.PORTAL: "portal",
}


def assemble_sacred(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType",
    tier: SiteTier = SiteTier.SMALL,
) -> Site:
    """Assemble a sacred site."""
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_sacred_surface(
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
        kind="sacred",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _tag_for(
    feature: "HexFeatureType | MinorFeatureType",
) -> str:
    if isinstance(feature, HexFeatureType):
        tag = _SACRED_MAJOR_TAGS.get(feature)
        if tag is not None:
            return tag
    if isinstance(feature, MinorFeatureType):
        return _SACRED_MINOR_TAGS.get(feature, "shrine")
    return "shrine"


def _build_sacred_surface(
    surface_id: str, width: int, height: int,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "sacred"
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

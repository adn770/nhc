"""Wayside site assembler.

Tiny sub-hex site with a single interactable tile on a walled
FIELD clearing. Covers WELL and SIGNPOST minor features today;
unknown features fall back to a generic ``landmark`` tag so the
sub-hex stays enterable. No buildings and no enclosure — the
walled perimeter is part of the surface Level itself rather than
a :class:`Enclosure`, matching the family generator's behaviour.

Wired through ``Game._enter_sub_hex_assembled`` from the unified
sub-hex dispatcher (see ``nhc_sites_unification_plan.md`` milestone
5).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


_WAYSIDE_TAGS: dict[MinorFeatureType, str] = {
    MinorFeatureType.WELL: "well",
    MinorFeatureType.SIGNPOST: "signpost",
}


def assemble_wayside(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType",
    tier: SiteTier = SiteTier.TINY,
) -> Site:
    """Assemble a wayside site.

    Returns a :class:`Site` with no buildings, a FIELD-tinted
    walled clearing as the surface, and one tile tagged with the
    matching interactable feature (``well`` / ``signpost`` /
    ``landmark``). The dispatcher is responsible for spawning the
    companion entity (``well_drink``, ``rumor_sign``) onto the
    tagged tile.
    """
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_wayside_surface(
        f"{site_id}_surface", width, height,
    )
    tag = _tag_for(feature)
    feature_xy = _pick_feature_tile(width, height, rng)
    fx, fy = feature_xy
    tile = surface.tile_at(fx, fy)
    if tile is not None:
        tile.terrain = Terrain.FLOOR
        tile.feature = tag
        tile.surface_type = SurfaceType.FIELD

    return Site(
        id=site_id,
        kind="wayside",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _tag_for(
    feature: "HexFeatureType | MinorFeatureType",
) -> str:
    if isinstance(feature, MinorFeatureType):
        return _WAYSIDE_TAGS.get(feature, "landmark")
    return "landmark"


def _build_wayside_surface(
    surface_id: str, width: int, height: int,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "wayside"
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
    """Centrepiece with a small jitter so repeated visits in the
    same flower don't all stamp the exact centre."""
    cx, cy = width // 2, height // 2
    jx = rng.randint(-1, 1)
    jy = rng.randint(-1, 1)
    return (cx + jx, cy + jy)

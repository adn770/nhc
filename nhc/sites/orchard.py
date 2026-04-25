"""Orchard site assembler.

Walled FIELD plaza with a central ``tree`` and a 3x3 grid of
scattered ``tree`` tiles around it -- planted rows, not random
forest. The dispatcher spawns an ``orchardist`` NPC adjacent to
the central tree.

Replaces the ORCHARD branch of the retired
``generate_inhabited_settlement_site``
(see ``nhc_sites_unification_plan.md`` milestone 4f).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


_TREE_SCATTER_STRIDE = 3


def assemble_orchard(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType" = (
        MinorFeatureType.ORCHARD
    ),
    tier: SiteTier = SiteTier.SMALL,
) -> Site:
    """Assemble an orchard site."""
    del feature  # one shape today; kwarg kept for assembler-API parity
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_orchard_surface(
        f"{site_id}_surface", width, height,
    )
    cx, cy = _pick_feature_tile(width, height, rng)
    center = surface.tile_at(cx, cy)
    if center is not None:
        center.terrain = Terrain.FLOOR
        center.feature = "tree"
        center.surface_type = SurfaceType.FIELD
    _scatter_orchard_trees(surface, (cx, cy), rng)

    return Site(
        id=site_id,
        kind="orchard",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _build_orchard_surface(
    surface_id: str, width: int, height: int,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "settlement"
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


def _scatter_orchard_trees(
    surface: Level, center: tuple[int, int], rng: random.Random,
) -> None:
    """Stamp a rough 3x3 grid of trees around ``center``.

    The grid stride is ~3 tiles so the rows read as planted, not
    random forest. The centre tile is already tagged by the caller;
    this fills the other eight slots, skipping any that fall on
    the perimeter or overlap a non-FLOOR tile.
    """
    cx, cy = center
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            tx = cx + dx * _TREE_SCATTER_STRIDE + rng.randint(-1, 1)
            ty = cy + dy * _TREE_SCATTER_STRIDE + rng.randint(-1, 1)
            tile = surface.tile_at(tx, ty)
            if tile is None or tile.terrain is not Terrain.FLOOR:
                continue
            if tile.feature:
                continue
            tile.feature = "tree"

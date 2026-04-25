"""Animal-den site assembler.

Cave-mouth lair on a walled FIELD clearing. Covers ANIMAL_DEN,
LAIR, NEST and BURROW minor features today. No buildings and no
enclosure; the ``den_mouth`` tile is the centrepiece. The
surface's ``metadata.faction`` is seeded from the biome so the
encounter system pulls the matching creature pool (forest beasts,
mountain beasts, undead in deadlands / swamp / marsh, etc.).

Replaces the retired ``generate_animal_den_site``
(see ``nhc_sites_unification_plan.md`` milestone 4c).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.hexcrawl.model import Biome, HexFeatureType, MinorFeatureType
from nhc.hexcrawl.sub_hex_sites import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site


def assemble_den(
    site_id: str, rng: random.Random,
    *,
    feature: "HexFeatureType | MinorFeatureType",
    biome: Biome,
    tier: SiteTier = SiteTier.MEDIUM,
) -> Site:
    """Assemble an animal-den site."""
    width, height = SITE_TIER_DIMS[tier]
    surface = _build_den_surface(
        f"{site_id}_surface", width, height, biome,
    )
    fx, fy = _pick_feature_tile(width, height, rng)
    tile = surface.tile_at(fx, fy)
    if tile is not None:
        tile.terrain = Terrain.FLOOR
        tile.feature = "den_mouth"
        tile.surface_type = SurfaceType.FIELD

    return Site(
        id=site_id,
        kind="den",
        buildings=[],
        surface=surface,
        enclosure=None,
    )


def _build_den_surface(
    surface_id: str, width: int, height: int, biome: Biome,
) -> Level:
    surface = Level.create_empty(
        id=surface_id, name=surface_id, depth=0,
        width=width, height=height,
    )
    surface.metadata.theme = "den"
    surface.metadata.prerevealed = True
    surface.metadata.faction = _biome_creature_faction(biome)
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


def _biome_creature_faction(biome: Biome) -> str:
    """Default creature faction for an animal-den level."""
    if biome in (Biome.DEADLANDS, Biome.SWAMP, Biome.MARSH):
        return "undead"
    if biome is Biome.FOREST:
        return "forest_beasts"
    if biome is Biome.MOUNTAIN:
        return "mountain_beasts"
    return "beasts"


def _pick_feature_tile(
    width: int, height: int, rng: random.Random,
) -> tuple[int, int]:
    cx, cy = width // 2, height // 2
    jx = rng.randint(-1, 1)
    jy = rng.randint(-1, 1)
    return (cx + jx, cy + jy)

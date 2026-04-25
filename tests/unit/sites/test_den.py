"""Den site assembler (animal_den, lair, nest, burrow).

A small cave-mouth on a FIELD-tinted clearing. No buildings, no
enclosure; the cave-mouth tile carries the ``den_mouth`` feature
tag and the surface metadata's ``faction`` is set to the biome's
default beast pool so the encounter system pulls the right
creatures.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import Biome, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.den import assemble_den


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleDenBasics:
    def test_returns_a_site(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert isinstance(site, Site)
        assert site.kind == "den"

    def test_has_no_buildings(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert site.enclosure is None

    def test_fits_in_medium_tier_dims(self):
        med_w, med_h = SITE_TIER_DIMS[SiteTier.MEDIUM]
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.width == med_w
        assert site.surface.height == med_h


class TestDenFeatureTile:
    def test_stamps_one_den_mouth_tile(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        mouths = _feature_tiles(site.surface, "den_mouth")
        assert len(mouths) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.NEST,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        mx, my = _feature_tiles(site.surface, "den_mouth")[0]
        tile = site.surface.tile_at(mx, my)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR


class TestDenSurface:
    def test_surface_tagged_as_field(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        surface = site.surface
        wall_count = sum(
            1 for y in range(surface.height)
            for x in range(surface.width)
            if (x in (0, surface.width - 1)
                or y in (0, surface.height - 1))
            and surface.tiles[y][x].terrain == Terrain.WALL
        )
        assert wall_count > 0


class TestDenFaction:
    def test_forest_biome_picks_forest_beasts(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.metadata.faction == "forest_beasts"

    def test_mountain_biome_picks_mountain_beasts(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.MOUNTAIN,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.metadata.faction == "mountain_beasts"

    def test_deadlands_biome_picks_undead(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.DEADLANDS,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.metadata.faction == "undead"

    def test_default_biome_picks_beasts(self):
        site = assemble_den(
            "d1", random.Random(1),
            feature=MinorFeatureType.LAIR,
            biome=Biome.GREENLANDS,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.metadata.faction == "beasts"


class TestDenDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_den(
            "d", random.Random(123),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        b = assemble_den(
            "d", random.Random(123),
            feature=MinorFeatureType.LAIR,
            biome=Biome.FOREST,
            tier=SiteTier.MEDIUM,
        )
        assert (
            _feature_tiles(a.surface, "den_mouth")
            == _feature_tiles(b.surface, "den_mouth")
        )

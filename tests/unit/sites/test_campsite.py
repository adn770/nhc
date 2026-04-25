"""Campsite site assembler — inhabited-settlement family.

Replaces the CAMPSITE branch of the retired
``generate_inhabited_settlement_site`` (M4f of sites-unification).
The campsite is a walled FIELD clearing with a single ``campfire``
centrepiece -- no interior walls, no scatter, sit-under-the-sky
shape.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.campsite import assemble_campsite


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleCampsiteBasics:
    def test_returns_a_site(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        assert isinstance(site, Site)
        assert site.kind == "campsite"

    def test_has_no_buildings(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        assert site.enclosure is None

    def test_fits_in_medium_tier_dims(self):
        med_w, med_h = SITE_TIER_DIMS[SiteTier.MEDIUM]
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.width == med_w
        assert site.surface.height == med_h


class TestCampsiteFeatureTile:
    def test_stamps_one_campfire_tile(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        fires = _feature_tiles(site.surface, "campfire")
        assert len(fires) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_campsite(
            "c1", random.Random(2),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        fx, fy = _feature_tiles(site.surface, "campfire")[0]
        tile = site.surface.tile_at(fx, fy)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR


class TestCampsiteSurface:
    def test_surface_tagged_as_field(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
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

    def test_no_interior_walls(self):
        """A campsite is open ground -- no interior walls."""
        site = assemble_campsite(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        surface = site.surface
        w, h = surface.width, surface.height
        for y in range(1, h - 1):
            for x in range(1, w - 1):
                tile = surface.tile_at(x, y)
                assert tile is not None
                assert tile.terrain != Terrain.WALL


class TestCampsiteDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_campsite(
            "c", random.Random(99),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        b = assemble_campsite(
            "c", random.Random(99),
            feature=MinorFeatureType.CAMPSITE,
            tier=SiteTier.MEDIUM,
        )
        assert (
            _feature_tiles(a.surface, "campfire")
            == _feature_tiles(b.surface, "campfire")
        )

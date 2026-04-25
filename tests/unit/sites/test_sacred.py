"""Sacred site assembler.

Single-monument centrepiece on a walled FIELD plaza. Covers the
SHRINE / STANDING_STONE / CAIRN minor features and the
CRYSTALS / STONES / WONDER / PORTAL major features under one
shape; the tier parameter accommodates both minor (SMALL) and
major (MEDIUM) callers.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import HexFeatureType, MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.sacred import assemble_sacred


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleSacredBasics:
    def test_returns_a_site(self):
        site = assemble_sacred(
            "s1", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert isinstance(site, Site)
        assert site.kind == "sacred"

    def test_has_no_buildings(self):
        site = assemble_sacred(
            "s1", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_sacred(
            "s1", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert site.enclosure is None

    def test_fits_in_medium_tier_dims(self):
        med_w, med_h = SITE_TIER_DIMS[SiteTier.MEDIUM]
        site = assemble_sacred(
            "s1", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert site.surface.width == med_w
        assert site.surface.height == med_h


class TestSacredFeatureTags:
    def test_minor_shrine(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "shrine")) == 1

    def test_minor_standing_stone(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.STANDING_STONE,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "monolith")) == 1

    def test_minor_cairn(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.CAIRN,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "cairn")) == 1

    def test_major_crystals(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=HexFeatureType.CRYSTALS,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "crystals")) == 1

    def test_major_stones_alias_monolith(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=HexFeatureType.STONES,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "monolith")) == 1

    def test_major_wonder(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=HexFeatureType.WONDER,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "wonder")) == 1

    def test_major_portal(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=HexFeatureType.PORTAL,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "portal")) == 1

    def test_unknown_feature_falls_back_to_shrine(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.MEDIUM,
        )
        assert len(_feature_tiles(site.surface, "shrine")) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        cx, cy = _feature_tiles(site.surface, "shrine")[0]
        tile = site.surface.tile_at(cx, cy)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR


class TestSacredSurface:
    def test_surface_tagged_as_field(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        site = assemble_sacred(
            "s", random.Random(1),
            feature=MinorFeatureType.SHRINE,
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


class TestSacredDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_sacred(
            "s", random.Random(99),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        b = assemble_sacred(
            "s", random.Random(99),
            feature=MinorFeatureType.SHRINE,
            tier=SiteTier.MEDIUM,
        )
        assert (
            _feature_tiles(a.surface, "shrine")
            == _feature_tiles(b.surface, "shrine")
        )

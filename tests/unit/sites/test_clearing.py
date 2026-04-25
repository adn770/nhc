"""Clearing site assembler (natural curiosities).

``assemble_clearing`` covers the MUSHROOM_RING / HERB_PATCH /
HOLLOW_LOG / BONE_PILE minor features — a single-tile centrepiece
on a FIELD-tinted walled clearing. No buildings, no enclosure,
no companion entities today (curiosities are passive tile tags).
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.clearing import assemble_clearing


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleClearingBasics:
    def test_returns_a_site(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.MUSHROOM_RING,
            tier=SiteTier.SMALL,
        )
        assert isinstance(site, Site)
        assert site.kind == "clearing"

    def test_has_no_buildings(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HERB_PATCH,
            tier=SiteTier.SMALL,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HOLLOW_LOG,
            tier=SiteTier.SMALL,
        )
        assert site.enclosure is None

    def test_fits_in_small_tier_dims(self):
        small_w, small_h = SITE_TIER_DIMS[SiteTier.SMALL]
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.BONE_PILE,
            tier=SiteTier.SMALL,
        )
        assert site.surface.width == small_w
        assert site.surface.height == small_h


class TestClearingFeatureTiles:
    def test_mushroom_ring_tag(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.MUSHROOM_RING,
            tier=SiteTier.SMALL,
        )
        assert len(_feature_tiles(site.surface, "mushrooms")) == 1

    def test_herb_patch_tag(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HERB_PATCH,
            tier=SiteTier.SMALL,
        )
        assert len(_feature_tiles(site.surface, "herbs")) == 1

    def test_hollow_log_tag(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HOLLOW_LOG,
            tier=SiteTier.SMALL,
        )
        assert len(_feature_tiles(site.surface, "hollow_log")) == 1

    def test_bone_pile_tag(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.BONE_PILE,
            tier=SiteTier.SMALL,
        )
        assert len(_feature_tiles(site.surface, "bones")) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HERB_PATCH,
            tier=SiteTier.SMALL,
        )
        tiles = _feature_tiles(site.surface, "herbs")
        hx, hy = tiles[0]
        tile = site.surface.tile_at(hx, hy)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR

    def test_unknown_feature_falls_back_to_mushrooms(self):
        """Keeps parity with the legacy family generator."""
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.CAIRN,
            tier=SiteTier.SMALL,
        )
        assert len(_feature_tiles(site.surface, "mushrooms")) == 1


class TestClearingSurface:
    def test_surface_tagged_as_field(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.MUSHROOM_RING,
            tier=SiteTier.SMALL,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        site = assemble_clearing(
            "c1", random.Random(1),
            feature=MinorFeatureType.HERB_PATCH,
            tier=SiteTier.SMALL,
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


class TestClearingDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_clearing(
            "c", random.Random(999),
            feature=MinorFeatureType.MUSHROOM_RING,
            tier=SiteTier.SMALL,
        )
        b = assemble_clearing(
            "c", random.Random(999),
            feature=MinorFeatureType.MUSHROOM_RING,
            tier=SiteTier.SMALL,
        )
        assert (
            _feature_tiles(a.surface, "mushrooms")
            == _feature_tiles(b.surface, "mushrooms")
        )

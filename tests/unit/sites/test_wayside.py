"""Wayside site assembler (well, signpost).

``assemble_wayside`` is the tiny-site sibling of the farm, mansion,
tower assemblers — a single-tile interactable (well or signpost)
sits on a FIELD-tinted clearing with no buildings and no
enclosure. Unifying the old ``generate_wayside_site`` family
generator onto this shape lets the sub-hex dispatcher route every
site through :func:`Site`.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.model import MinorFeatureType
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.wayside import assemble_wayside


def _feature_tiles(surface, tag: str) -> list[tuple[int, int]]:
    return [
        (x, y)
        for y, row in enumerate(surface.tiles)
        for x, t in enumerate(row) if t.feature == tag
    ]


class TestAssembleWaysideBasics:
    def test_returns_a_site(self):
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        assert isinstance(site, Site)
        assert site.kind == "wayside"

    def test_has_no_buildings(self):
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        assert site.buildings == []

    def test_has_no_enclosure(self):
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        assert site.enclosure is None

    def test_fits_in_small_tier_dims(self):
        small_w, small_h = SITE_TIER_DIMS[SiteTier.SMALL]
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        assert site.surface.width == small_w
        assert site.surface.height == small_h


class TestWaysideFeatureTile:
    def test_well_stamps_single_well_tile(self):
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        wells = _feature_tiles(site.surface, "well")
        assert len(wells) == 1

    def test_signpost_stamps_single_signpost_tile(self):
        site = assemble_wayside(
            "w1", random.Random(7),
            feature=MinorFeatureType.SIGNPOST,
            tier=SiteTier.SMALL,
        )
        posts = _feature_tiles(site.surface, "signpost")
        assert len(posts) == 1

    def test_feature_tile_is_walkable(self):
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        wells = _feature_tiles(site.surface, "well")
        wx, wy = wells[0]
        tile = site.surface.tile_at(wx, wy)
        assert tile is not None
        assert tile.terrain == Terrain.FLOOR

    def test_unknown_feature_falls_back_to_landmark(self):
        """Any feature the wayside doesn't recognise gets a
        ``landmark`` tag so the sub-hex is still interactable."""
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.CAIRN,
            tier=SiteTier.SMALL,
        )
        landmarks = _feature_tiles(site.surface, "landmark")
        assert len(landmarks) == 1


class TestWaysideDeterminism:
    def test_same_seed_same_feature_tile(self):
        a = assemble_wayside(
            "w", random.Random(1234),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        b = assemble_wayside(
            "w", random.Random(1234),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        wells_a = _feature_tiles(a.surface, "well")
        wells_b = _feature_tiles(b.surface, "well")
        assert wells_a == wells_b


class TestWaysideSurface:
    def test_surface_tagged_as_field(self):
        """Walkable interior tiles carry SurfaceType.FIELD so the
        SVG renderer picks up the field tint."""
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
            tier=SiteTier.SMALL,
        )
        field_tiles = sum(
            1 for row in site.surface.tiles for t in row
            if t.surface_type == SurfaceType.FIELD
        )
        assert field_tiles > 0

    def test_perimeter_has_walls(self):
        """The 1-tile perimeter stays WALL so the player can't step
        off the map by accident. Leave-site uses the overland exit
        mechanic at the edge instead."""
        site = assemble_wayside(
            "w1", random.Random(1),
            feature=MinorFeatureType.WELL,
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

"""Tier parameter on ``assemble_farm``.

The farm assembler accepts a ``tier`` kwarg so the same code can
produce a sub-hex farm (``SiteTier.SMALL``) and the macro farm
(``SiteTier.MEDIUM``, current defaults). SMALL drops the barn and
the descent; MEDIUM keeps current behaviour.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.hexcrawl.sub_hex_sites import SITE_TIER_DIMS, SiteTier
from nhc.sites._site import Site
from nhc.sites.farm import (
    FARM_BARN_PROBABILITY,
    FARM_DESCENT_PROBABILITY,
    assemble_farm,
)


def _count_surface(site: Site, kind: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == kind
    )


class TestSmallFarm:
    def test_returns_a_site(self):
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        assert isinstance(site, Site)
        assert site.kind == "farm"

    def test_fits_in_small_tier_dims(self):
        """Surface level fits within the sub-hex SMALL tier envelope.

        The sub-hex dispatcher sizes family-site levels using
        ``SITE_TIER_DIMS``; a unified SMALL farm must fit so the
        dispatcher does not need to crop it.
        """
        small_w, small_h = SITE_TIER_DIMS[SiteTier.SMALL]
        for seed in range(20):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert site.surface.width <= small_w
            assert site.surface.height <= small_h

    def test_has_no_barn(self):
        """SMALL farms are a farmhouse only — no barn."""
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            assert len(site.buildings) == 1

    def test_has_no_descent(self):
        """SMALL farms never spawn a cellar descent."""
        for seed in range(40):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.SMALL,
            )
            farmhouse = site.buildings[0]
            assert farmhouse.descent is None

    def test_surface_has_field_tiles(self):
        """SMALL farms tag the open surface as FIELD."""
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        total_floor = sum(
            1 for row in site.surface.tiles
            for t in row if t.terrain == Terrain.FLOOR
        )
        field = _count_surface(site, SurfaceType.FIELD)
        assert total_floor > 0
        assert field > 0

    def test_surface_has_garden_ring(self):
        """SMALL farms stamp GARDEN tiles around the farmhouse."""
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        gardens = _count_surface(site, SurfaceType.GARDEN)
        assert gardens >= 1


class TestMediumFarmUnchanged:
    def test_default_tier_is_medium(self):
        """Calling without ``tier`` keeps the existing macro farm."""
        default = assemble_farm("f1", random.Random(42))
        explicit = assemble_farm(
            "f1", random.Random(42), tier=SiteTier.MEDIUM,
        )
        assert len(default.buildings) == len(explicit.buildings)
        assert default.surface.width == explicit.surface.width
        assert default.surface.height == explicit.surface.height

    def test_medium_surface_is_30x22(self):
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.MEDIUM,
        )
        assert site.surface.width == 30
        assert site.surface.height == 22

    def test_medium_barn_probability_unchanged(self):
        trials = 200
        count = 0
        for seed in range(trials):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.MEDIUM,
            )
            if len(site.buildings) == 2:
                count += 1
        ratio = count / trials
        medium_prob = FARM_BARN_PROBABILITY[SiteTier.MEDIUM]
        assert abs(ratio - medium_prob) < 0.15

    def test_medium_descent_probability_unchanged(self):
        trials = 300
        count = 0
        for seed in range(trials):
            site = assemble_farm(
                "f1", random.Random(seed), tier=SiteTier.MEDIUM,
            )
            if any(b.descent is not None for b in site.buildings):
                count += 1
        ratio = count / trials
        medium_prob = FARM_DESCENT_PROBABILITY[SiteTier.MEDIUM]
        assert abs(ratio - medium_prob) < 0.08

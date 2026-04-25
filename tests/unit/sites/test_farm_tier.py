"""Tier parameter on ``assemble_farm``.

The farm assembler accepts a ``tier`` kwarg so the same code can
produce a sub-hex farm (``SiteTier.SMALL``) and the macro farm
(``SiteTier.MEDIUM``, current defaults). SMALL drops the barn and
the descent; MEDIUM keeps current behaviour.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites._types import SITE_TIER_DIMS, SiteTier
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


class TestSmallFarmFarmhouse:
    """The SMALL farm renders a real farmhouse: walled interior, a
    single door_closed on the perimeter, and a matching surface door
    painted by :func:`paint_surface_doors`. These replace the old
    ``_stamp_farmhouse`` behaviour from the sub-hex family generator.
    """

    def test_farmhouse_ground_has_wall_perimeter(self):
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        ground = site.buildings[0].ground
        wall_count = sum(
            1 for row in ground.tiles for t in row
            if t.terrain == Terrain.WALL
        )
        assert wall_count > 0

    def test_farmhouse_ground_has_one_entry_door(self):
        """Exactly one ``door_closed`` sits on the farmhouse
        perimeter — the surface entry."""
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        farmhouse = site.buildings[0]
        ground = farmhouse.ground
        perim = farmhouse.shared_perimeter()
        perim_doors = [
            (x, y) for y, row in enumerate(ground.tiles)
            for x, t in enumerate(row)
            if t.feature == "door_closed" and (x, y) in perim
        ]
        assert len(perim_doors) == 1

    def test_farmhouse_door_sits_next_to_a_wall(self):
        """The door_closed tile has at least one WALL neighbour on
        the ground — otherwise it is a floating door."""
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        ground = site.buildings[0].ground
        doors = [
            (x, y) for y, row in enumerate(ground.tiles)
            for x, t in enumerate(row)
            if t.feature == "door_closed"
        ]
        assert doors
        dx, dy = doors[0]
        neighbours = [
            ground.tile_at(dx + ox, dy + oy)
            for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        ]
        wall_neighbours = [
            t for t in neighbours
            if t is not None and t.terrain == Terrain.WALL
        ]
        assert wall_neighbours


class TestSmallFarmSurfaceDoor:
    """``paint_surface_doors`` stamps a ``door_closed`` on the
    surface side of the farmhouse so bumping it transitions the
    player into the farmhouse interior."""

    def test_surface_has_at_least_one_door_closed(self):
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        doors = [
            (x, y) for y, row in enumerate(site.surface.tiles)
            for x, t in enumerate(row) if t.feature == "door_closed"
        ]
        assert doors, "surface must carry the building door"

    def test_surface_door_is_registered_in_building_doors(self):
        site = assemble_farm(
            "f1", random.Random(1), tier=SiteTier.SMALL,
        )
        doors = [
            (x, y) for y, row in enumerate(site.surface.tiles)
            for x, t in enumerate(row) if t.feature == "door_closed"
        ]
        assert doors[0] in site.building_doors


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

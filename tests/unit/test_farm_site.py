"""Tests for the farm site assembler (M12).

See design/building_generator.md section 5.2. A farm is 1-2 small
wood-interior buildings (farmhouse + optional barn) surrounded by
a large FIELD region with a few GARDEN tiles around the
farmhouse. No enclosure; rare cellar descent (~10%); base shape
is rectangular or L-shaped.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import LShape, RectShape, SurfaceType, Terrain
from nhc.hexcrawl.sub_hex_sites import SiteTier
from nhc.sites._site import Site
from nhc.sites.farm import (
    FARM_BARN_PROBABILITY,
    FARM_DESCENT_PROBABILITY,
    assemble_farm,
)


def _surface_count(site: Site, surface: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == surface
    )


class TestAssembleFarmBasics:
    def test_returns_site_with_farm_kind(self):
        site = assemble_farm("f1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "farm"

    def test_no_enclosure(self):
        site = assemble_farm("f1", random.Random(1))
        assert site.enclosure is None

    def test_has_one_or_two_buildings(self):
        for seed in range(30):
            site = assemble_farm("f1", random.Random(seed))
            assert 1 <= len(site.buildings) <= 2


class TestFarmBuildings:
    def test_floor_counts_within_1_to_2(self):
        for seed in range(30):
            site = assemble_farm("f1", random.Random(seed))
            for b in site.buildings:
                assert 1 <= len(b.floors) <= 2

    def test_interior_is_wood(self):
        for seed in range(20):
            site = assemble_farm("f1", random.Random(seed))
            for b in site.buildings:
                assert b.interior_floor == "wood"
                for f in b.floors:
                    assert f.interior_floor == "wood"

    def test_shape_is_rect_or_lshape(self):
        seen: set[str] = set()
        for seed in range(60):
            site = assemble_farm("f1", random.Random(seed))
            for b in site.buildings:
                seen.add(type(b.base_shape).__name__)
        assert seen <= {"RectShape", "LShape"}

    def test_farmhouse_has_entry_door_on_perimeter(self):
        """At least one ground-floor door sits on the perimeter — the
        surface entry. Interior doors from the partitioner may sit
        off-perimeter."""
        site = assemble_farm("f1", random.Random(1))
        farmhouse = site.buildings[0]
        ground = farmhouse.ground
        perim = farmhouse.shared_perimeter()
        perim_doors = [
            (x, y) for y, row in enumerate(ground.tiles)
            for x, t in enumerate(row)
            if t.feature == "door_closed" and (x, y) in perim
        ]
        assert len(perim_doors) >= 1

    def test_building_validate_passes(self):
        site = assemble_farm("f1", random.Random(1))
        for b in site.buildings:
            b.validate()


class TestFarmSurface:
    def test_field_dominates_surface(self):
        """Fields cover a large fraction of the surface level."""
        site = assemble_farm("f1", random.Random(1))
        total_floor = sum(
            1 for row in site.surface.tiles
            for t in row if t.terrain == Terrain.FLOOR
        )
        field = _surface_count(site, SurfaceType.FIELD)
        assert total_floor > 0
        assert field / total_floor > 0.3

    def test_garden_ring_exists(self):
        """A few GARDEN tiles surround the farmhouse."""
        site = assemble_farm("f1", random.Random(1))
        gardens = _surface_count(site, SurfaceType.GARDEN)
        assert gardens >= 3

    def test_surface_has_no_street(self):
        """Farms have no streets or cobblestones."""
        site = assemble_farm("f1", random.Random(1))
        assert _surface_count(site, SurfaceType.STREET) == 0

    def test_surface_svg_has_no_walled_island_strokes(self):
        """FIELD and GARDEN tiles must not trigger the thick WALL
        stroke around them -- same pattern as STREET on town /
        keep surfaces."""
        from nhc.rendering._svg_helpers import WALL_WIDTH
        from nhc.rendering.svg import render_floor_svg
        site = assemble_farm("f1", random.Random(7))
        svg = render_floor_svg(site.surface, seed=7)
        assert f'stroke-width="{WALL_WIDTH}"' not in svg

    def test_building_footprint_not_in_surface_field(self):
        """FIELD tiles do not overlap building footprints."""
        site = assemble_farm("f1", random.Random(1))
        for b in site.buildings:
            footprint = b.base_shape.floor_tiles(b.base_rect)
            for (x, y) in footprint:
                if site.surface.in_bounds(x, y):
                    t = site.surface.tiles[y][x]
                    assert t.surface_type != SurfaceType.FIELD
                    assert t.surface_type != SurfaceType.GARDEN


class TestFarmDescent:
    def test_descent_probability_roughly_matches_spec(self):
        count = 0
        trials = 300
        for seed in range(trials):
            site = assemble_farm("f1", random.Random(seed))
            if any(b.descent is not None for b in site.buildings):
                count += 1
        ratio = count / trials
        # Spec says ~10%; allow wide tolerance.
        assert abs(ratio - FARM_DESCENT_PROBABILITY[SiteTier.MEDIUM]) < 0.08

    def test_descent_lives_on_farmhouse_only(self):
        """If a barn is present, descent is never on the barn."""
        from nhc.hexcrawl.model import DungeonRef
        for seed in range(300):
            site = assemble_farm("f1", random.Random(seed))
            if len(site.buildings) < 2:
                continue
            barn = site.buildings[1]
            assert barn.descent is None


class TestFarmBarn:
    def test_barn_probability_roughly_matches_spec(self):
        count = 0
        trials = 200
        for seed in range(trials):
            site = assemble_farm("f1", random.Random(seed))
            if len(site.buildings) == 2:
                count += 1
        ratio = count / trials
        assert abs(ratio - FARM_BARN_PROBABILITY[SiteTier.MEDIUM]) < 0.15

    def test_barn_smaller_than_farmhouse(self):
        """When a barn is present, it is not larger than the farmhouse."""
        for seed in range(80):
            site = assemble_farm("f1", random.Random(seed))
            if len(site.buildings) < 2:
                continue
            farmhouse, barn = site.buildings
            farmhouse_area = (
                farmhouse.base_rect.width * farmhouse.base_rect.height
            )
            barn_area = barn.base_rect.width * barn.base_rect.height
            assert barn_area <= farmhouse_area
            return
        pytest.skip("No barn generated in 80 seeds")


class TestFarmDeterminism:
    def test_same_seed_same_building_count(self):
        s1 = assemble_farm("f1", random.Random(42))
        s2 = assemble_farm("f1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)

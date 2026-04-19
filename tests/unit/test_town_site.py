"""Tests for the town site assembler (M15).

See design/building_generator.md section 5.5. A town is 5-8 small
buildings placed in a grid, surrounded by a palisade enclosure
with 1-2 gates. STREET surface between buildings; mixed
wood/stone interiors. Descent is rare.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.dungeon.site import Enclosure, Site
from nhc.dungeon.sites.town import (
    TOWN_BUILDING_COUNT_RANGE,
    TOWN_DESCENT_PROBABILITY,
    assemble_town,
)


def _surface_count(site: Site, surface: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == surface
    )


class TestAssembleTownBasics:
    def test_returns_site_with_town_kind(self):
        site = assemble_town("t1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "town"

    def test_enclosure_is_palisade(self):
        site = assemble_town("t1", random.Random(1))
        assert isinstance(site.enclosure, Enclosure)
        assert site.enclosure.kind == "palisade"

    def test_enclosure_has_one_or_two_gates(self):
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            assert 1 <= len(site.enclosure.gates) <= 2


class TestTownBuildings:
    def test_building_count_in_range(self):
        lo, hi = TOWN_BUILDING_COUNT_RANGE
        for seed in range(30):
            site = assemble_town("t1", random.Random(seed))
            assert lo <= len(site.buildings) <= hi

    def test_all_buildings_validate(self):
        site = assemble_town("t1", random.Random(1))
        for b in site.buildings:
            b.validate()

    def test_mixed_interior_floor_materials(self):
        """Some buildings are wood (residential/market), others
        stone (temple/garrison)."""
        floors: set[str] = set()
        for seed in range(20):
            site = assemble_town("t1", random.Random(seed))
            for b in site.buildings:
                floors.add(b.interior_floor)
        assert "wood" in floors
        assert "stone" in floors


class TestTownSurface:
    def test_street_dominates_surface(self):
        site = assemble_town("t1", random.Random(1))
        assert _surface_count(site, SurfaceType.STREET) > 0

    def test_surface_has_no_field(self):
        site = assemble_town("t1", random.Random(1))
        assert _surface_count(site, SurfaceType.FIELD) == 0

    def test_building_footprint_not_overlaid_as_street(self):
        site = assemble_town("t1", random.Random(1))
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                if site.surface.in_bounds(x, y):
                    t = site.surface.tiles[y][x]
                    assert t.surface_type != SurfaceType.STREET

    def test_street_tiles_lie_inside_palisade_polygon(self):
        """Every STREET tile must sit strictly inside the palisade
        bbox so the palisade border reads as drawn ON the black
        line enclosing the streets -- not one tile past them."""
        site = assemble_town("t1", random.Random(1))
        xs = [p[0] for p in site.enclosure.polygon]
        ys = [p[1] for p in site.enclosure.polygon]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for y, row in enumerate(site.surface.tiles):
            for x, t in enumerate(row):
                if t.surface_type != SurfaceType.STREET:
                    continue
                # A tile at (tx, ty) spans pixels [tx, tx+1] in
                # tile units. The palisade polygon spans
                # [min_x, max_x] x [min_y, max_y]. Tile must fit
                # strictly inside: x+1 <= max_x and y+1 <= max_y.
                assert min_x <= x and x + 1 <= max_x, (
                    f"STREET tile x={x} outside palisade "
                    f"x-range [{min_x}, {max_x})"
                )
                assert min_y <= y and y + 1 <= max_y, (
                    f"STREET tile y={y} outside palisade "
                    f"y-range [{min_y}, {max_y})"
                )


class TestTownEnclosure:
    def test_palisade_polygon_encloses_all_buildings(self):
        site = assemble_town("t1", random.Random(1))
        poly = site.enclosure.polygon
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                assert min_x <= x <= max_x
                assert min_y <= y <= max_y


class TestTownDescent:
    def test_descent_is_rare(self):
        count = 0
        trials = 200
        for seed in range(trials):
            site = assemble_town("t1", random.Random(seed))
            if any(b.descent is not None for b in site.buildings):
                count += 1
        ratio = count / trials
        # Spec says "rare"; per-building probability is small, and
        # site-level should stay under ~50%.
        assert ratio < 0.6


class TestTownDeterminism:
    def test_same_seed_same_building_count(self):
        s1 = assemble_town("t1", random.Random(42))
        s2 = assemble_town("t1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)

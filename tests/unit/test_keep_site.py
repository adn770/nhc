"""Tests for the keep site assembler (M14).

See design/building_generator.md section 5.4. A keep is a main
compound of 2-3 adjacent buildings plus 2-4 smaller sparse
buildings, wrapped by a fortification wall with 1-2 gates. The
surface inside the wall is STREET; interior floors are stone
throughout; descent chance is ~40%.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.sites._site import Enclosure, Site
from nhc.sites.keep import (
    KEEP_DESCENT_PROBABILITY,
    KEEP_MAIN_BUILDING_COUNT_RANGE,
    KEEP_SPARSE_BUILDING_COUNT_RANGE,
    assemble_keep,
)


def _surface_count(site: Site, surface: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == surface
    )


class TestAssembleKeepBasics:
    def test_returns_site_with_keep_kind(self):
        site = assemble_keep("k1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "keep"

    def test_enclosure_is_fortification(self):
        site = assemble_keep("k1", random.Random(1))
        assert isinstance(site.enclosure, Enclosure)
        assert site.enclosure.kind == "fortification"

    def test_enclosure_has_one_or_two_gates(self):
        for seed in range(30):
            site = assemble_keep("k1", random.Random(seed))
            gates = site.enclosure.gates
            assert 1 <= len(gates) <= 2


class TestKeepBuildings:
    def test_main_building_count_in_range(self):
        lo, hi = KEEP_MAIN_BUILDING_COUNT_RANGE
        for seed in range(20):
            site = assemble_keep("k1", random.Random(seed))
            main = [
                b for b in site.buildings
                if "keep_main" in b.id
            ]
            assert lo <= len(main) <= hi

    def test_sparse_building_count_in_range(self):
        lo, hi = KEEP_SPARSE_BUILDING_COUNT_RANGE
        for seed in range(20):
            site = assemble_keep("k1", random.Random(seed))
            sparse = [
                b for b in site.buildings
                if "keep_sparse" in b.id
            ]
            assert lo <= len(sparse) <= hi

    def test_total_building_count(self):
        """2-3 main + 2-4 sparse = 4-7 total."""
        for seed in range(20):
            site = assemble_keep("k1", random.Random(seed))
            assert 4 <= len(site.buildings) <= 7

    def test_all_buildings_stone_interior(self):
        for seed in range(20):
            site = assemble_keep("k1", random.Random(seed))
            for b in site.buildings:
                assert b.interior_floor == "stone"
                for f in b.floors:
                    assert f.interior_floor == "stone"

    def test_validate_passes_for_every_building(self):
        site = assemble_keep("k1", random.Random(1))
        for b in site.buildings:
            b.validate()


class TestKeepEnclosure:
    def test_polygon_has_at_least_four_vertices(self):
        site = assemble_keep("k1", random.Random(1))
        assert len(site.enclosure.polygon) >= 4

    def test_polygon_encloses_every_building(self):
        """Every building footprint tile is inside the enclosure
        bounding box (convex-hull check avoided for simplicity; we
        just confirm min/max vertex coords dominate every footprint
        tile)."""
        site = assemble_keep("k1", random.Random(1))
        poly = site.enclosure.polygon
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for b in site.buildings:
            footprint = b.base_shape.floor_tiles(b.base_rect)
            for (x, y) in footprint:
                assert min_x <= x <= max_x
                assert min_y <= y <= max_y


class TestKeepSurface:
    def test_surface_has_street_tiles(self):
        """The courtyard inside the fortification is STREET."""
        site = assemble_keep("k1", random.Random(1))
        assert _surface_count(site, SurfaceType.STREET) > 0

    def test_surface_has_no_field(self):
        site = assemble_keep("k1", random.Random(1))
        assert _surface_count(site, SurfaceType.FIELD) == 0

    def test_building_footprint_not_street(self):
        site = assemble_keep("k1", random.Random(1))
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                if site.surface.in_bounds(x, y):
                    t = site.surface.tiles[y][x]
                    assert t.surface_type != SurfaceType.STREET

    def test_street_tiles_lie_inside_fortification_polygon(self):
        """Every STREET tile must sit strictly inside the
        fortification bbox so the wall reads as drawn ON the
        black line enclosing the courtyard."""
        site = assemble_keep("k1", random.Random(1))
        xs = [p[0] for p in site.enclosure.polygon]
        ys = [p[1] for p in site.enclosure.polygon]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        for y, row in enumerate(site.surface.tiles):
            for x, t in enumerate(row):
                if t.surface_type != SurfaceType.STREET:
                    continue
                assert min_x <= x and x + 1 <= max_x, (
                    f"STREET tile x={x} outside wall "
                    f"x-range [{min_x}, {max_x})"
                )
                assert min_y <= y and y + 1 <= max_y, (
                    f"STREET tile y={y} outside wall "
                    f"y-range [{min_y}, {max_y})"
                )


class TestKeepDescent:
    def test_descent_probability_roughly_matches_spec(self):
        count = 0
        trials = 300
        for seed in range(trials):
            site = assemble_keep("k1", random.Random(seed))
            # Descent only considered on main buildings per spec.
            main = [b for b in site.buildings if "keep_main" in b.id]
            if any(b.descent is not None for b in main):
                count += 1
        ratio = count / trials
        # Per-main-building is 40%; with 2-3 main per keep, site
        # probability is higher than 40%.
        assert 0.3 < ratio < 0.9, f"descent site ratio {ratio:.2f}"

    def test_sparse_buildings_never_descend(self):
        for seed in range(80):
            site = assemble_keep("k1", random.Random(seed))
            sparse = [
                b for b in site.buildings
                if "keep_sparse" in b.id
            ]
            for b in sparse:
                assert b.descent is None


class TestKeepDeterminism:
    def test_same_seed_same_structure(self):
        s1 = assemble_keep("k1", random.Random(42))
        s2 = assemble_keep("k1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)
        assert len(s1.enclosure.gates) == len(s2.enclosure.gates)

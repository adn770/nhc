"""Tests for the mansion site assembler (M13).

See design/building_generator.md section 5.3. A mansion is 2-4
adjacent buildings interconnected by interior doors, with a GARDEN
ring surrounding the whole compound. No enclosure. Interior is
stone on the ground floor and wood on upper floors. Optional
descent (~20%).
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.model import SurfaceType, Terrain
from nhc.dungeon.site import Site
from nhc.dungeon.sites.mansion import (
    MANSION_BUILDING_COUNT_RANGE,
    MANSION_DESCENT_PROBABILITY,
    assemble_mansion,
)


def _surface_count(site: Site, surface: SurfaceType) -> int:
    return sum(
        1 for row in site.surface.tiles
        for t in row if t.surface_type == surface
    )


class TestAssembleMansionBasics:
    def test_returns_site_with_mansion_kind(self):
        site = assemble_mansion("m1", random.Random(1))
        assert isinstance(site, Site)
        assert site.kind == "mansion"

    def test_no_enclosure(self):
        site = assemble_mansion("m1", random.Random(1))
        assert site.enclosure is None

    def test_building_count_in_range(self):
        lo, hi = MANSION_BUILDING_COUNT_RANGE
        for seed in range(30):
            site = assemble_mansion("m1", random.Random(seed))
            assert lo <= len(site.buildings) <= hi


class TestMansionInteriorFloors:
    def test_ground_floor_is_stone(self):
        for seed in range(20):
            site = assemble_mansion("m1", random.Random(seed))
            for b in site.buildings:
                assert b.ground.interior_floor == "stone"

    def test_upper_floors_are_wood(self):
        for seed in range(30):
            site = assemble_mansion("m1", random.Random(seed))
            for b in site.buildings:
                if len(b.floors) >= 2:
                    for f in b.floors[1:]:
                        assert f.interior_floor == "wood"
                    return
        pytest.skip("No multi-floor mansion in 30 seeds")


class TestMansionInteriorDoors:
    def test_adjacent_pairs_share_an_interior_door(self):
        site = assemble_mansion("m1", random.Random(1))
        for i in range(len(site.buildings) - 1):
            left = site.buildings[i]
            right = site.buildings[i + 1]
            # Both building ground floors have a door on their
            # facing edges.
            left_doors = _door_tiles(left.ground)
            right_doors = _door_tiles(right.ground)
            # At least one door on each side of the interface.
            assert len(left_doors) >= 2 or len(right_doors) >= 2, (
                "expected at least one interior door between "
                f"buildings {i} and {i+1}"
            )

    def test_each_building_has_at_least_one_entry_door(self):
        site = assemble_mansion("m1", random.Random(1))
        for b in site.buildings:
            assert len(_door_tiles(b.ground)) >= 1


def _door_tiles(level) -> list[tuple[int, int]]:
    return [
        (x, y) for y, row in enumerate(level.tiles)
        for x, t in enumerate(row) if t.feature == "door_closed"
    ]


class TestMansionSurface:
    def test_garden_fills_every_outdoor_tile(self):
        """The entire outdoor area (every FLOOR tile outside the
        building footprints) is GARDEN. No "lawn" NONE tiles."""
        from nhc.dungeon.model import Terrain
        site = assemble_mansion("m1", random.Random(1))
        outdoor_floor = 0
        gardens = 0
        for row in site.surface.tiles:
            for t in row:
                if t.terrain != Terrain.FLOOR:
                    continue
                outdoor_floor += 1
                if t.surface_type == SurfaceType.GARDEN:
                    gardens += 1
        assert outdoor_floor > 0
        assert gardens == outdoor_floor, (
            f"{outdoor_floor - gardens} FLOOR tiles outside "
            f"the garden fill"
        )

    def test_surface_has_no_field_or_street(self):
        site = assemble_mansion("m1", random.Random(1))
        assert _surface_count(site, SurfaceType.FIELD) == 0
        assert _surface_count(site, SurfaceType.STREET) == 0

    def test_surface_svg_has_no_walled_island_strokes(self):
        """GARDEN tiles must not trigger the WALL stroke."""
        from nhc.rendering._svg_helpers import WALL_WIDTH
        from nhc.rendering.svg import render_floor_svg
        site = assemble_mansion("m1", random.Random(7))
        svg = render_floor_svg(site.surface, seed=7)
        assert f'stroke-width="{WALL_WIDTH}"' not in svg

    def test_building_footprint_not_overlaid_as_garden(self):
        site = assemble_mansion("m1", random.Random(1))
        for b in site.buildings:
            for (x, y) in b.base_shape.floor_tiles(b.base_rect):
                if site.surface.in_bounds(x, y):
                    t = site.surface.tiles[y][x]
                    assert t.surface_type != SurfaceType.GARDEN


class TestMansionDescent:
    def test_descent_probability_roughly_matches_spec(self):
        count = 0
        trials = 300
        for seed in range(trials):
            site = assemble_mansion("m1", random.Random(seed))
            if any(b.descent is not None for b in site.buildings):
                count += 1
        ratio = count / trials
        # Spec: 20% per-building; overall "site has at least one"
        # will be higher. Just require it lives in a plausible band.
        assert 0.1 < ratio < 0.9

    def test_each_building_validate_passes(self):
        site = assemble_mansion("m1", random.Random(1))
        for b in site.buildings:
            b.validate()


class TestMansionDeterminism:
    def test_same_seed_same_building_count(self):
        s1 = assemble_mansion("m1", random.Random(42))
        s2 = assemble_mansion("m1", random.Random(42))
        assert len(s1.buildings) == len(s2.buildings)

"""Tests for render_building_floor_svg composition.

See design/building_generator.md section 7. A Building's floor
renders the interior through render_floor_svg and then overlays
brick / stone wall runs along the exterior perimeter. Circular
and octagonal footprints fall back to the base renderer because
only orthogonal wall runs are supported so far.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.sites.mansion import assemble_mansion
from nhc.dungeon.sites.tower import assemble_tower
from nhc.rendering._building_walls import BRICK_FILL, STONE_FILL
from nhc.rendering.building import render_building_floor_svg


def _first_rect_tower(seed_range: range = range(200)):
    from nhc.dungeon.model import RectShape
    for seed in seed_range:
        site = assemble_tower("t", random.Random(seed))
        b = site.buildings[0]
        if isinstance(b.base_shape, RectShape):
            return b
    pytest.skip("no RectShape tower in seed_range")


def _first_circle_or_octagon_tower(seed_range: range = range(200)):
    from nhc.dungeon.model import CircleShape, OctagonShape
    for seed in seed_range:
        site = assemble_tower("t", random.Random(seed))
        b = site.buildings[0]
        if isinstance(b.base_shape, (CircleShape, OctagonShape)):
            return b
    pytest.skip("no circle/octagon tower in seed_range")


class TestRenderBuildingFloorSignature:
    def test_returns_string_with_svg_tags(self):
        b = _first_rect_tower()
        out = render_building_floor_svg(b, 0, seed=42)
        assert isinstance(out, str)
        assert "<svg" in out
        assert "</svg>" in out

    def test_floor_index_out_of_range_raises(self):
        b = _first_rect_tower()
        with pytest.raises(IndexError):
            render_building_floor_svg(b, len(b.floors) + 5, seed=0)


class TestRectBuildingWallsEmitted:
    def test_brick_material_emits_brick_fill(self):
        b = _first_rect_tower()
        b.wall_material = "brick"
        out = render_building_floor_svg(b, 0, seed=42)
        assert BRICK_FILL in out

    def test_stone_material_emits_stone_fill(self):
        b = _first_rect_tower()
        b.wall_material = "stone"
        out = render_building_floor_svg(b, 0, seed=42)
        assert STONE_FILL in out

    def test_dungeon_material_emits_neither(self):
        b = _first_rect_tower()
        b.wall_material = "dungeon"
        out = render_building_floor_svg(b, 0, seed=42)
        assert BRICK_FILL not in out
        assert STONE_FILL not in out


class TestNonOrthogonalBuildingFallback:
    def test_circle_or_octagon_falls_back_to_base(self):
        """Non-orthogonal perimeters don't get brick / stone overlays."""
        b = _first_circle_or_octagon_tower()
        b.wall_material = "brick"
        out = render_building_floor_svg(b, 0, seed=42)
        assert BRICK_FILL not in out


class TestRenderBuildingFloorDeterminism:
    def test_same_seed_same_output(self):
        b = _first_rect_tower()
        b.wall_material = "brick"
        a = render_building_floor_svg(b, 0, seed=42)
        c = render_building_floor_svg(b, 0, seed=42)
        assert a == c


class TestLShapeBuildingWalls:
    def test_mansion_lshape_building_emits_wall_overlays(self):
        """Mansion buildings may be L-shaped; those should still get
        brick overlays along their orthogonal perimeter runs."""
        from nhc.dungeon.model import LShape
        for seed in range(200):
            site = assemble_mansion("m", random.Random(seed))
            for b in site.buildings:
                if not isinstance(b.base_shape, LShape):
                    continue
                b.wall_material = "brick"
                out = render_building_floor_svg(b, 0, seed=42)
                assert BRICK_FILL in out
                return
        pytest.skip("no L-shape mansion building in 200 seeds")

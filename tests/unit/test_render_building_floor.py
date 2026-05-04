"""Tests for render_building_floor_svg composition.

See design/building_generator.md section 7. A Building's floor
renders the interior through render_floor_svg and then overlays
brick / stone wall runs along the exterior perimeter. Circular
and octagonal footprints fall back to the base renderer because
only orthogonal wall runs are supported so far.
"""

from __future__ import annotations

import random
import re

import pytest

from nhc.sites.mansion import assemble_mansion
from nhc.sites.tower import assemble_tower
from nhc.rendering._building_walls import (
    BRICK_FILL,
    MASONRY_WALL_THICKNESS,
    STONE_FILL,
)
from nhc.rendering._svg_helpers import CELL, PADDING
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


class TestNonOrthogonalBuildingWalls:
    def test_octagon_tower_emits_brick_overlay(self):
        """Octagon and circle perimeters now get masonry overlays
        via the diagonal-run path."""
        from nhc.dungeon.model import OctagonShape
        for seed in range(200):
            site = assemble_tower("t", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, OctagonShape):
                b.wall_material = "brick"
                out = render_building_floor_svg(b, 0, seed=42)
                assert BRICK_FILL in out
                return
        pytest.skip("no OctagonShape tower in 200 seeds")

    def test_circle_tower_emits_brick_overlay(self):
        from nhc.dungeon.model import CircleShape
        for seed in range(200):
            site = assemble_tower("t", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, CircleShape):
                b.wall_material = "brick"
                out = render_building_floor_svg(b, 0, seed=42)
                assert BRICK_FILL in out
                return
        pytest.skip("no CircleShape tower in 200 seeds")

    def test_octagon_wall_has_rotated_units(self):
        """Octagon has 4 diagonal edges -> some rects must carry
        a rotate() transform."""
        from nhc.dungeon.model import OctagonShape
        for seed in range(200):
            site = assemble_tower("t", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, OctagonShape):
                b.wall_material = "brick"
                out = render_building_floor_svg(b, 0, seed=42)
                assert "rotate(" in out
                return
        pytest.skip("no OctagonShape tower in 200 seeds")


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

    def test_lshape_building_floor_has_interior_clip(self):
        """LShape building floors must build a non-empty dungeon
        polygon so wood plank seams (and other floor detail) get
        clipped to the interior and don't bleed onto walls."""
        from nhc.dungeon.model import LShape
        from nhc.rendering._cave_geometry import (
            _build_cave_wall_geometry,
        )
        from nhc.rendering._dungeon_polygon import (
            _build_dungeon_polygon,
        )
        for seed in range(200):
            site = assemble_mansion("m", random.Random(seed))
            for b in site.buildings:
                if not isinstance(b.base_shape, LShape):
                    continue
                level = b.floors[0]
                cave_rng = random.Random(seed + 0x5A17E5)
                _, cave_poly, cave_tiles = (
                    _build_cave_wall_geometry(level, cave_rng)
                )
                dp = _build_dungeon_polygon(
                    level,
                    cave_wall_poly=cave_poly,
                    cave_tiles=cave_tiles,
                )
                assert dp is not None
                assert not dp.is_empty, (
                    "LShape level produced an empty dungeon polygon"
                )
                return
        pytest.skip("no L-shape mansion building in 200 seeds")

class TestBuildingFloorsSkipDungeonEffects:
    def _rect_building(self):
        from nhc.dungeon.model import RectShape
        for seed in range(200):
            site = assemble_tower("t", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, RectShape):
                return b
        pytest.skip("no RectShape tower in 200 seeds")

    def test_no_shadow_elements(self):
        """Building floors don't render the 8%-opacity offset
        shadow that normal dungeons use."""
        b = self._rect_building()
        out = render_building_floor_svg(b, 0, seed=42)
        assert 'opacity="0.08"' not in out

    def test_no_hatch_clip(self):
        """Building floors don't emit the cross-hatch clip or
        underlay."""
        from nhc.rendering._svg_helpers import HATCH_UNDERLAY
        b = self._rect_building()
        out = render_building_floor_svg(b, 0, seed=42)
        assert "hatch-clip" not in out
        assert HATCH_UNDERLAY not in out

    def test_regular_dungeon_level_still_has_shadows_and_hatch(self):
        """Sanity check: a plain Level without building_id still
        gets shadows + hatching."""
        from nhc.dungeon.generator import GenerationParams
        from nhc.dungeon.generators.bsp import BSPGenerator
        from nhc.rendering._svg_helpers import HATCH_UNDERLAY
        from nhc.rendering.svg import render_floor_svg
        level = BSPGenerator().generate(
            GenerationParams(seed=42, shape_variety=0.5),
        )
        svg = render_floor_svg(level, seed=42)
        assert 'opacity="0.08"' in svg
        assert HATCH_UNDERLAY in svg


class TestBuildingFloorsSkipBonesAndSkulls:
    def test_no_bones_or_skulls_across_many_keep_floors(self):
        """Scan every floor of every keep building across many
        seeds. Keep buildings are stone-interior, so they would
        otherwise hit the full thematic-detail path. None of them
        should emit a bones or skulls group."""
        from nhc.sites.keep import assemble_keep
        for seed in range(30):
            site = assemble_keep("k", random.Random(seed))
            for bi, b in enumerate(site.buildings):
                for fi in range(len(b.floors)):
                    out = render_building_floor_svg(
                        b, fi, seed=seed + fi,
                    )
                    assert "detail-bones" not in out, (
                        f"bones on keep seed={seed} b{bi} f{fi}"
                    )
                    assert "detail-skulls" not in out, (
                        f"skulls on keep seed={seed} b{bi} f{fi}"
                    )

    def test_no_floor_stones_across_many_keep_floors(self):
        """Stone keep floors also skip the dungeon-style floor
        stone ellipses (FLOOR_STONE_FILL)."""
        from nhc.sites.keep import assemble_keep
        from nhc.rendering._svg_helpers import FLOOR_STONE_FILL
        for seed in range(30):
            site = assemble_keep("k", random.Random(seed))
            for bi, b in enumerate(site.buildings):
                for fi in range(len(b.floors)):
                    out = render_building_floor_svg(
                        b, fi, seed=seed + fi,
                    )
                    assert FLOOR_STONE_FILL not in out, (
                        f"floor stones on keep seed={seed} "
                        f"b{bi} f{fi}"
                    )


def _brick_rects(svg: str) -> list[dict]:
    """Extract <rect> elements whose fill is the brick colour."""
    rects = []
    for m in re.finditer(r'<rect([^/]*)/>', svg):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        if attrs.get("fill") == BRICK_FILL:
            rects.append(attrs)
    return rects


class TestBrickWallsExtendPastCorners:
    def _rect_building(self):
        from nhc.dungeon.model import RectShape
        for seed in range(200):
            site = assemble_tower("t", random.Random(seed))
            b = site.buildings[0]
            if isinstance(b.base_shape, RectShape):
                b.wall_material = "brick"
                return b
        pytest.skip("no RectShape tower in 200 seeds")

    def test_top_edge_bricks_extend_past_left_vertex(self):
        """The top wall starts to the LEFT of the NW polygon vertex
        by thickness/2 so it overlaps the left wall's upper end."""
        b = self._rect_building()
        out = render_building_floor_svg(b, 0, seed=42)
        rect = b.base_rect
        nw_x = PADDING + rect.x * CELL
        nw_y = PADDING + rect.y * CELL
        ext = MASONRY_WALL_THICKNESS / 2
        # Find the leftmost brick rect whose y-center matches the top
        # edge y. It should start at x <= nw_x - ext + small tolerance.
        top_y_center = nw_y
        min_x = None
        for a in _brick_rects(out):
            y = float(a["y"])
            h = float(a["height"])
            # Two strips sit symmetrically around the edge line, so
            # any rect whose centre is within thickness/2 of the
            # edge belongs to this wall band.
            if abs(y + h / 2 - top_y_center) > MASONRY_WALL_THICKNESS / 2:
                continue
            x = float(a["x"])
            if min_x is None or x < min_x:
                min_x = x
        assert min_x is not None
        assert min_x <= nw_x - ext + 0.2, (
            f"leftmost brick x={min_x:.1f}, expected <= "
            f"{nw_x - ext + 0.2:.1f}"
        )

    def test_top_edge_bricks_extend_past_right_vertex(self):
        b = self._rect_building()
        out = render_building_floor_svg(b, 0, seed=42)
        rect = b.base_rect
        ne_x = PADDING + rect.x2 * CELL
        ne_y = PADDING + rect.y * CELL
        ext = MASONRY_WALL_THICKNESS / 2
        # Find the rightmost brick rect whose y-center matches the
        # top edge y. Its right edge should reach x >= ne_x + ext
        # (within tolerance).
        top_y_center = ne_y
        max_right = None
        for a in _brick_rects(out):
            y = float(a["y"])
            h = float(a["height"])
            # Two strips sit symmetrically around the edge line, so
            # any rect whose centre is within thickness/2 of the
            # edge belongs to this wall band.
            if abs(y + h / 2 - top_y_center) > MASONRY_WALL_THICKNESS / 2:
                continue
            right = float(a["x"]) + float(a["width"])
            if max_right is None or right > max_right:
                max_right = right
        assert max_right is not None
        assert max_right >= ne_x + ext - 0.2, (
            f"rightmost brick right={max_right:.1f}, expected >= "
            f"{ne_x + ext - 0.2:.1f}"
        )

    def test_corner_square_fully_covered_by_at_least_one_wall(self):
        """The thick x thick square at the NW polygon vertex is
        covered by wall bricks (from the top run and/or the left
        run) -- no empty L-shape in the corner."""
        b = self._rect_building()
        out = render_building_floor_svg(b, 0, seed=42)
        rect = b.base_rect
        nw_x = PADDING + rect.x * CELL
        nw_y = PADDING + rect.y * CELL
        thick = MASONRY_WALL_THICKNESS
        # The NW corner square spans (nw_x - thick/2, nw_y - thick/2)
        # to (nw_x + thick/2, nw_y + thick/2). For fullness, check
        # all four thick/2 x thick/2 quadrants have a brick covering
        # their centre.
        brick_rects = _brick_rects(out)

        def _covered(px: float, py: float) -> bool:
            for a in brick_rects:
                x = float(a["x"])
                y = float(a["y"])
                w = float(a["width"])
                h = float(a["height"])
                if x <= px <= x + w and y <= py <= y + h:
                    return True
            return False

        for dx in (-thick / 4, thick / 4):
            for dy in (-thick / 4, thick / 4):
                assert _covered(nw_x + dx, nw_y + dy), (
                    f"NW corner point ({nw_x + dx:.1f}, "
                    f"{nw_y + dy:.1f}) not covered by any brick"
                )

"""Tests for walkable-surface rendering on Tile.surface_type.

See design/building_generator.md section 7.3. M8 wires the new
SurfaceType enum into the existing street cobblestone renderer so
that a tile with ``surface_type = SurfaceType.STREET`` is drawn
with cobblestones regardless of the legacy ``is_street`` boolean.
"""

from __future__ import annotations

import math
import random
import re

from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering.svg import render_floor_svg


def _blank_level(w: int = 10, h: int = 10) -> Level:
    level = Level.create_empty("t", "t", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, w, h))]
    return level


class TestSurfaceTypeStreetRendering:
    def test_surface_type_street_triggers_cobblestone(self):
        level = _blank_level()
        level.tiles[5][5].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level, seed=42)
        # Cobblestone stroke colour is the canonical street marker.
        assert "#8A7A6A" in svg

    def test_legacy_is_street_still_works(self):
        level = _blank_level()
        level.tiles[5][5].is_street = True
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" in svg

    def test_no_surface_or_flag_means_no_cobblestones(self):
        level = _blank_level()
        # Leave every tile with surface_type = NONE and is_street = False.
        svg = render_floor_svg(level, seed=42)
        # Without any street tile, the cobblestone group does not appear.
        assert "#8A7A6A" not in svg

    def test_both_flags_set_still_renders(self):
        level = _blank_level()
        level.tiles[3][3].is_street = True
        level.tiles[3][3].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" in svg

    def test_non_street_surface_types_do_not_render_cobbles(self):
        level = _blank_level()
        # FIELD, GARDEN, PALISADE, FORTIFICATION must not pick up the
        # street renderer; their own renderers land in later
        # milestones.
        for st in (
            SurfaceType.FIELD,
            SurfaceType.GARDEN,
            SurfaceType.PALISADE,
            SurfaceType.FORTIFICATION,
        ):
            tile = Tile(terrain=Terrain.FLOOR, surface_type=st)
            level.tiles[4][4] = tile
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" not in svg


class TestFieldSurface:
    def test_field_tile_emits_green_tint(self):
        from nhc.rendering._floor_detail import FIELD_TINT
        level = _blank_level()
        level.tiles[4][4].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        assert FIELD_TINT in svg

    def test_no_field_no_green(self):
        from nhc.rendering._floor_detail import FIELD_TINT
        level = _blank_level()
        svg = render_floor_svg(level, seed=42)
        assert FIELD_TINT not in svg

    def test_field_tile_emits_stones(self):
        """Fields are lightly scattered with visible stones."""
        from nhc.rendering._floor_detail import (
            FIELD_STONE_FILL,
        )
        level = _blank_level(20, 20)
        for y in range(20):
            for x in range(20):
                level.tiles[y][x].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        # Over 400 field tiles, the stone probability should produce
        # several visible stones.
        assert FIELD_STONE_FILL in svg

    def test_field_surface_skips_cobblestones(self):
        """Field tiles never get the street's cobblestone style."""
        level = _blank_level()
        level.tiles[5][5].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" not in svg


class TestGardenSurface:
    def test_garden_tile_emits_green_tint(self):
        from nhc.rendering._floor_detail import GARDEN_TINT
        level = _blank_level()
        level.tiles[4][4].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert GARDEN_TINT in svg

    def test_garden_tile_emits_wobbly_grid(self):
        """Garden uses dungeon-style line detail in its own colour."""
        from nhc.rendering._floor_detail import GARDEN_LINE_STROKE
        level = _blank_level(20, 20)
        for y in range(20):
            for x in range(20):
                level.tiles[y][x].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert GARDEN_LINE_STROKE in svg

    def test_garden_surface_skips_cobblestones(self):
        level = _blank_level()
        level.tiles[5][5].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" not in svg

    def test_garden_surface_skips_field_stones(self):
        """Gardens use lines, not stones -- the field stone marker
        should not appear when only GARDEN tiles are present."""
        from nhc.rendering._floor_detail import FIELD_STONE_FILL
        level = _blank_level(10, 10)
        for y in range(10):
            for x in range(10):
                level.tiles[y][x].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert FIELD_STONE_FILL not in svg


class TestFieldVsGardenPalette:
    def test_field_and_garden_use_green_family(self):
        from nhc.rendering._floor_detail import FIELD_TINT, GARDEN_TINT
        # Both live in the green family; they may match exactly or
        # differ slightly, but neither should be a grey or brown.
        for hx in (FIELD_TINT, GARDEN_TINT):
            assert hx.startswith("#")
            # crude "green family" check: green channel dominates
            r, g, b = (
                int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16),
            )
            assert g >= r and g >= b


class TestWoodInteriorFloor:
    def test_wood_floor_emits_wood_fill(self):
        from nhc.rendering._floor_detail import WOOD_FLOOR_FILL
        level = _blank_level()
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_FLOOR_FILL in svg

    def test_wood_floor_emits_seam_stroke(self):
        from nhc.rendering._floor_detail import WOOD_SEAM_STROKE
        level = _blank_level(30, 30)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_SEAM_STROKE in svg

    def test_stone_floor_has_no_wood_colors(self):
        from nhc.rendering._floor_detail import (
            WOOD_FLOOR_FILL, WOOD_SEAM_STROKE,
        )
        level = _blank_level()
        assert level.interior_floor == "stone"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_FLOOR_FILL not in svg
        assert WOOD_SEAM_STROKE not in svg

    def test_wood_floor_suppresses_crack_detail(self):
        """Wood floors have no dungeon-style crack scratches."""
        level = _blank_level(20, 20)
        level.interior_floor = "wood"
        wood_svg = render_floor_svg(level, seed=42)
        stone_level = _blank_level(20, 20)
        stone_svg = render_floor_svg(stone_level, seed=42)
        # Wood SVG should not contain the scratch/crack "<g" section
        # produced by _render_floor_detail when interior_floor ==
        # "stone". Count a crude proxy: hand-scratched path strokes
        # at 0.3-0.7 width are scratches.
        def _count_hand_scratches(svg: str) -> int:
            return (
                svg.count('stroke-width="0.3"')
                + svg.count('stroke-width="0.4"')
                + svg.count('stroke-width="0.5"')
                + svg.count('stroke-width="0.6"')
                + svg.count('stroke-width="0.7"')
            )
        # Wood has far fewer hand-drawn detail strokes
        assert _count_hand_scratches(wood_svg) < _count_hand_scratches(
            stone_svg,
        )


class TestWoodParquetConstants:
    def test_plank_width_is_quarter_tile(self):
        from nhc.rendering._floor_detail import WOOD_PLANK_WIDTH_PX
        from nhc.rendering._svg_helpers import CELL
        assert math.isclose(WOOD_PLANK_WIDTH_PX, CELL / 4)

    def test_plank_length_is_two_and_half_tiles(self):
        from nhc.rendering._floor_detail import WOOD_PLANK_LENGTH_PX
        from nhc.rendering._svg_helpers import CELL
        assert math.isclose(WOOD_PLANK_LENGTH_PX, CELL * 2.5)

    def test_plank_offset_is_fifth_tile(self):
        from nhc.rendering._floor_detail import WOOD_PLANK_OFFSET_PX
        from nhc.rendering._svg_helpers import CELL
        assert math.isclose(WOOD_PLANK_OFFSET_PX, CELL / 5)


class TestWoodGrainEffect:
    def test_grain_light_colour_present(self):
        from nhc.rendering._floor_detail import WOOD_GRAIN_LIGHT
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_GRAIN_LIGHT in svg

    def test_grain_dark_colour_present(self):
        from nhc.rendering._floor_detail import WOOD_GRAIN_DARK
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_GRAIN_DARK in svg

    def test_grain_colours_differ_from_base_and_seam(self):
        from nhc.rendering._floor_detail import (
            WOOD_FLOOR_FILL, WOOD_GRAIN_DARK, WOOD_GRAIN_LIGHT,
            WOOD_SEAM_STROKE,
        )
        # Distinct from base fill and from the seam stroke so the
        # grain layer is visually separate.
        assert WOOD_GRAIN_LIGHT != WOOD_FLOOR_FILL
        assert WOOD_GRAIN_DARK != WOOD_FLOOR_FILL
        assert WOOD_GRAIN_LIGHT != WOOD_SEAM_STROKE
        assert WOOD_GRAIN_DARK != WOOD_SEAM_STROKE

    def test_grain_uses_low_opacity(self):
        from nhc.rendering._floor_detail import WOOD_GRAIN_OPACITY
        # Subtle grain: well below 1.0, well above 0.
        assert 0.1 < WOOD_GRAIN_OPACITY < 0.8

    def test_stone_floor_has_no_grain_colors(self):
        from nhc.rendering._floor_detail import (
            WOOD_GRAIN_DARK, WOOD_GRAIN_LIGHT,
        )
        level = _blank_level(20, 6)
        assert level.interior_floor == "stone"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_GRAIN_LIGHT not in svg
        assert WOOD_GRAIN_DARK not in svg


class TestWoodParquetPattern:
    def test_horizontal_room_emits_many_plank_end_lines(self):
        """A wide wood room produces more vertical plank-end seams
        than the 3 horizontal seams the old renderer emitted."""
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        # Count <line> inside the wood-seam group.
        lines = re.findall(r'<line\s[^/]*/>', svg)
        # Roughly: 20 tiles wide * 32 = 640px. Plank length 80.
        # Per strip ~8 vertical seams. 6 tiles tall * 32 / 8 = 24
        # strips. Plus 23 horizontal strip boundaries.
        # Total roughly 200+ lines.
        assert len(lines) > 50

    def test_parquet_strips_use_plank_width(self):
        """Distance between consecutive horizontal seam y-coords
        inside the wood-seam group equals the plank width."""
        from nhc.rendering._floor_detail import (
            WOOD_PLANK_WIDTH_PX, WOOD_SEAM_STROKE,
        )
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        # Restrict scan to the wood-seam <g ...> ... </g> block so
        # unrelated floor-grid lines don't leak in.
        group_start = svg.find(f'stroke="{WOOD_SEAM_STROKE}"')
        assert group_start > 0
        group_end = svg.find("</g>", group_start)
        segment = svg[group_start:group_end]
        ys = set()
        for m in re.finditer(
            r'<line x1="[0-9.]+" y1="([0-9.]+)" '
            r'x2="[0-9.]+" y2="([0-9.]+)"', segment,
        ):
            y1, y2 = float(m.group(1)), float(m.group(2))
            if math.isclose(y1, y2):
                ys.add(round(y1, 2))
        assert len(ys) >= 2
        ys_sorted = sorted(ys)
        for a, b in zip(ys_sorted, ys_sorted[1:]):
            assert math.isclose(
                b - a, WOOD_PLANK_WIDTH_PX, abs_tol=0.1,
            ), f"strip gap {b - a:.2f}"

"""Tests for walkable-surface rendering on Tile.surface_type.

See design/building_generator.md section 7.3. M8 wires the new
SurfaceType enum into the existing street cobblestone renderer so
that a tile with ``surface_type = SurfaceType.STREET`` is drawn
with cobblestones regardless of the legacy ``is_street`` boolean.
"""

from __future__ import annotations

import random

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

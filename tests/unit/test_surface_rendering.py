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

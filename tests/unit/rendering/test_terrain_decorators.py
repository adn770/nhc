"""Portability tests for the Phase 4 terrain decorators.

Each terrain (water / grass / lava / chasm) renders the same
decorator output regardless of floor kind: drop a single tile of
the matching terrain into a synthetic level and the corresponding
decorator group appears in the SVG.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    Level, Rect, Room, RectShape, SurfaceType, Terrain, Tile,
)
from nhc.rendering.svg import render_floor_svg


def _level_with_one_tile(terrain: Terrain) -> Level:
    level = Level.create_empty("L", "L", 1, 6, 6)
    for y in range(6):
        for x in range(6):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.tiles[3][3] = Tile(terrain=terrain)
    level.rooms = [Room(id="r1", rect=Rect(0, 0, 6, 6))]
    return level


class TestTerrainDecoratorPortability:
    def test_water_tile_renders_water_class(self) -> None:
        svg = render_floor_svg(_level_with_one_tile(Terrain.WATER))
        assert 'class="terrain-water"' in svg

    def test_grass_tile_renders_grass_class(self) -> None:
        svg = render_floor_svg(_level_with_one_tile(Terrain.GRASS))
        assert 'class="terrain-grass"' in svg

    def test_lava_tile_renders_lava_class(self) -> None:
        svg = render_floor_svg(_level_with_one_tile(Terrain.LAVA))
        assert 'class="terrain-lava"' in svg

    def test_chasm_tile_renders_chasm_class(self) -> None:
        svg = render_floor_svg(_level_with_one_tile(Terrain.CHASM))
        assert 'class="terrain-chasm"' in svg


class TestRoomCorridorBucketing:
    """The terrain detail layer splits per-tile fragments into the
    ``"room"`` and ``"corridor"`` buckets via the tile_bucket
    classifier. Room fragments are wrapped in the dungeon-poly
    clip group; corridor fragments stay unclipped so they don't
    end up cropped at the doorways."""

    def test_room_water_uses_clip_group(self) -> None:
        level = _level_with_one_tile(Terrain.WATER)
        # The single water tile defaults to surface_type.NONE
        # which buckets as ``room``.
        svg = render_floor_svg(level)
        assert 'id="terrain-detail-clip"' in svg

    def test_corridor_water_skips_clip_group(self) -> None:
        level = Level.create_empty("L", "L", 1, 6, 6)
        for y in range(6):
            for x in range(6):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        # Single water tile, marked CORRIDOR -> bucket "corridor".
        level.tiles[3][3] = Tile(
            terrain=Terrain.WATER,
            surface_type=SurfaceType.CORRIDOR,
        )
        # No rooms -> dungeon_poly empty -> no clip group ever
        # appears (the helper bypasses the clip when poly is empty).
        svg = render_floor_svg(level)
        assert 'id="terrain-detail-clip"' not in svg
        # But the corridor terrain fragment still emits its class.
        assert 'class="terrain-water"' in svg

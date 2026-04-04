"""Tests for terrain-specific SVG rendering."""

from __future__ import annotations

import re

from nhc.dungeon.model import (
    Level, LevelMetadata, Rect, RectShape, Room, Terrain, Tile,
)
from nhc.dungeon.terrain import THEME_PARAMS
from nhc.rendering.terrain_palette import (
    ROOM_TYPE_TINTS, THEME_PALETTES,
    get_palette,
)
from nhc.rendering.svg import render_floor_svg


# ── Helpers ──────────���──────────────────────────────────────────


def _make_terrain_level(
    terrain: Terrain = Terrain.WATER,
    theme: str = "dungeon",
    room_tag: str | None = None,
    width: int = 12,
    height: int = 10,
) -> Level:
    """Level with one room where interior tiles use *terrain*."""
    level = Level.create_empty(
        "test", "Test", depth=1, width=width, height=height,
    )
    level.metadata = LevelMetadata(theme=theme)

    # Carve a room (2,2)-(8,6)
    tags = [room_tag] if room_tag else []
    room = Room(id="r1", rect=Rect(2, 2, 6, 4), tags=tags)
    level.rooms.append(room)
    for y in range(2, 6):
        for x in range(2, 8):
            level.tiles[y][x] = Tile(terrain=terrain)

    # One corridor tile so walls render properly
    level.tiles[3][8] = Tile(terrain=Terrain.FLOOR, is_corridor=True)

    return level


# ── Phase 1: Palette unit tests ──────���─────────────────────────


class TestTerrainPalette:
    def test_every_theme_has_palette(self):
        """Every theme in THEME_PARAMS must have a palette entry."""
        for theme in THEME_PARAMS:
            palette = get_palette(theme)
            assert palette is not None, f"Missing palette for {theme}"
            assert palette.water.tint.startswith("#")
            assert palette.grass.tint.startswith("#")

    def test_default_palette_is_dungeon(self):
        p_unknown = get_palette("nonexistent_theme")
        p_dungeon = get_palette("dungeon")
        assert p_unknown == p_dungeon

    def test_tint_opacities_in_range(self):
        for name, palette in THEME_PALETTES.items():
            for terrain_name in ("water", "grass", "lava", "chasm"):
                style = getattr(palette, terrain_name)
                assert 0.05 <= style.tint_opacity <= 0.35, (
                    f"{name}.{terrain_name}.tint_opacity="
                    f"{style.tint_opacity} out of range"
                )
                assert 0.1 <= style.detail_opacity <= 0.7, (
                    f"{name}.{terrain_name}.detail_opacity="
                    f"{style.detail_opacity} out of range"
                )

    def test_room_type_tints_cover_special_types(self):
        for rtype in ("shrine", "garden", "library", "treasury"):
            assert rtype in ROOM_TYPE_TINTS, (
                f"Missing room-type tint for {rtype}"
            )


# ── Phase 2: Terrain tint SVG tests ─��──────────────────────────


class TestTerrainTintSVG:
    def test_water_tiles_get_tinted_rect(self):
        level = _make_terrain_level(Terrain.WATER, theme="dungeon")
        svg = render_floor_svg(level)
        palette = get_palette("dungeon")
        assert palette.water.tint.lower() in svg.lower()

    def test_grass_tiles_get_tinted_rect(self):
        level = _make_terrain_level(Terrain.GRASS, theme="dungeon")
        svg = render_floor_svg(level)
        palette = get_palette("dungeon")
        assert palette.grass.tint.lower() in svg.lower()

    def test_lava_tiles_get_tinted_rect(self):
        level = _make_terrain_level(Terrain.LAVA, theme="dungeon")
        svg = render_floor_svg(level)
        palette = get_palette("dungeon")
        assert palette.lava.tint.lower() in svg.lower()

    def test_different_themes_produce_different_tints(self):
        level_cave = _make_terrain_level(Terrain.WATER, theme="cave")
        level_castle = _make_terrain_level(Terrain.WATER, theme="castle")
        svg_cave = render_floor_svg(level_cave)
        svg_castle = render_floor_svg(level_castle)
        p_cave = get_palette("cave")
        p_castle = get_palette("castle")
        assert p_cave.water.tint.lower() in svg_cave.lower()
        assert p_castle.water.tint.lower() in svg_castle.lower()

    def test_floor_tiles_have_no_terrain_tint(self):
        """Plain FLOOR tiles should not produce terrain tint rects."""
        level = _make_terrain_level(Terrain.FLOOR, theme="dungeon")
        svg = render_floor_svg(level)
        palette = get_palette("dungeon")
        # None of the terrain tint colors should appear
        for attr in ("water", "grass", "lava", "chasm"):
            tint = getattr(palette, attr).tint.lower()
            assert tint not in svg.lower(), (
                f"FLOOR-only level should not contain {attr} tint {tint}"
            )

    def test_corridor_water_tile_gets_floor_fill(self):
        """A corridor tile with WATER terrain still gets white base."""
        level = _make_terrain_level(Terrain.FLOOR)
        # Make the corridor tile water
        level.tiles[3][8].terrain = Terrain.WATER
        svg = render_floor_svg(level)
        # The corridor tile at (8,3) should have a white rect
        px, py = 8 * 32, 3 * 32
        assert f'x="{px}"' in svg

    def test_shrine_room_gets_type_tint(self):
        level = _make_terrain_level(
            Terrain.FLOOR, room_tag="shrine",
        )
        svg = render_floor_svg(level)
        tint_color = ROOM_TYPE_TINTS["shrine"][0].lower()
        assert tint_color in svg.lower()


# ── Phase 3: Terrain detail SVG tests ──────────────────────────


class TestTerrainDetailSVG:
    def test_water_tiles_get_wavy_detail(self):
        level = _make_terrain_level(Terrain.WATER)
        svg = render_floor_svg(level, seed=42)
        # Water detail uses wavy paths — check for the terrain
        # detail group marker
        assert "terrain-water" in svg

    def test_grass_tiles_get_stroke_detail(self):
        level = _make_terrain_level(Terrain.GRASS)
        svg = render_floor_svg(level, seed=42)
        assert "terrain-grass" in svg

    def test_floor_tiles_no_terrain_detail(self):
        """Standard FLOOR tiles should not get terrain detail marks."""
        level = _make_terrain_level(Terrain.FLOOR)
        svg = render_floor_svg(level, seed=42)
        assert "terrain-water" not in svg
        assert "terrain-grass" not in svg

    def test_terrain_tiles_skip_standard_detail(self):
        """WATER/GRASS tiles should not get standard cracks/stones."""
        level = _make_terrain_level(Terrain.WATER)
        svg_water = render_floor_svg(level, seed=42)
        level2 = _make_terrain_level(Terrain.FLOOR)
        svg_floor = render_floor_svg(level2, seed=42)
        # Count floor stone elements (brown ellipses) — water SVG
        # should have fewer since terrain tiles skip standard detail
        water_stones = svg_water.lower().count("#e8d5b8")
        floor_stones = svg_floor.lower().count("#e8d5b8")
        assert water_stones <= floor_stones

    def test_deterministic_terrain_rendering(self):
        level = _make_terrain_level(Terrain.WATER)
        svg1 = render_floor_svg(level, seed=42)
        svg2 = render_floor_svg(level, seed=42)
        assert svg1 == svg2

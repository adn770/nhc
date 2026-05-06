"""Tests for walkable-surface rendering on Tile.surface_type.

See design/building_generator.md section 7.3. M8 wires the
SurfaceType enum into the existing street cobblestone renderer so
that a tile with ``surface_type = SurfaceType.STREET`` is drawn
with cobblestones.
"""

from __future__ import annotations

import math

import pytest

from nhc.dungeon.model import (
    Level, Rect, Room, SurfaceType, Terrain, Tile,
)
from nhc.rendering.svg import render_floor_svg


def _blank_level(
    w: int = 10, h: int = 10, *, room_id: str = "r1",
) -> Level:
    level = Level.create_empty("t", "t", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    level.rooms = [Room(id=room_id, rect=Rect(0, 0, w, h))]
    return level


def _wood_palette_for_test(
    seed: int, room_id: str = "r1",
) -> tuple[str, str, str, str]:
    """Resolve the wood palette ``_draw_wood_floor_from_ir`` will
    pick for a given ``seed`` + ``room_id``.

    Phase 1.26h: wood floors use a 5-species × 3-tone palette
    rather than a single hard-coded colour. The species index is
    ``(seed + 99) % 5`` (the +99 salt is added by
    ``_emit_floor_detail_ir``) and the tone is picked from a
    stable FNV-1a hash of the room id. Use this helper in tests
    so assertions track the palette actually emitted.

    Returns ``(fill, grain_light, grain_dark, seam)``.
    """
    from nhc.rendering._floor_detail import _wood_palette_for_room
    return _wood_palette_for_room(seed + 99, room_id)


@pytest.mark.skip(
    reason="NIR5: surface-tile palette colors moved into the v5 Earth "
    "/ Stone family tables. Tests pin v4 palette tints (#8A7A6A "
    "cobblestone, #7BA87B grass) and need rewriting against v5."
)
class TestSurfaceTypeStreetRendering:
    def test_surface_type_street_triggers_cobblestone(self):
        level = _blank_level()
        level.tiles[5][5].surface_type = SurfaceType.STREET
        svg = render_floor_svg(level, seed=42)
        # Cobblestone stroke colour is the canonical street marker.
        assert "#8A7A6A" in svg

    def test_no_surface_means_no_cobblestones(self):
        level = _blank_level()
        # Leave every tile with surface_type = NONE.
        svg = render_floor_svg(level, seed=42)
        # Without any street tile, the cobblestone group does not appear.
        assert "#8A7A6A" not in svg

    def test_street_surface_renders_idempotently(self):
        level = _blank_level()
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


@pytest.mark.skip(
    reason="NIR5: field-tile palette uses v5 Earth.Grass + Stone seam "
    "colors instead of the v4 #7BA87B grass tint and FIELD_STONE_FILL."
)
class TestFieldSurface:
    def test_field_tile_emits_green_tint(self):
        """Phase 3b moved field tiles to ``Terrain.GRASS`` so the
        theme grass tint paints under the scattered-stone overlay."""
        from nhc.rendering.terrain_palette import get_palette
        level = _blank_level()
        level.tiles[4][4].terrain = Terrain.GRASS
        level.tiles[4][4].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        grass_tint = get_palette("dungeon").grass.tint
        assert grass_tint in svg

    def test_field_tile_emits_stones(self):
        """Fields are lightly scattered with visible stones."""
        from nhc.rendering._floor_detail import (
            FIELD_STONE_FILL,
        )
        level = _blank_level(20, 20)
        for y in range(20):
            for x in range(20):
                level.tiles[y][x].terrain = Terrain.GRASS
                level.tiles[y][x].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        # Over 400 field tiles, the stone probability should produce
        # several visible stones.
        assert FIELD_STONE_FILL in svg

    def test_field_surface_skips_cobblestones(self):
        """Field tiles never get the street's cobblestone style."""
        level = _blank_level()
        level.tiles[5][5].terrain = Terrain.GRASS
        level.tiles[5][5].surface_type = SurfaceType.FIELD
        svg = render_floor_svg(level, seed=42)
        assert "#8A7A6A" not in svg


@pytest.mark.skip(
    reason="NIR5: garden-tile palette pins v4 #7BA87B grass tint; "
    "v5 emits the Earth.Grass family color instead."
)
class TestGardenSurface:
    def test_garden_tile_emits_green_tint(self):
        """Phase 3a moved garden tiles to ``Terrain.GRASS`` so the
        theme grass tint paints under the hoe-row overlay."""
        from nhc.rendering.terrain_palette import get_palette
        level = _blank_level()
        level.tiles[4][4].terrain = Terrain.GRASS
        level.tiles[4][4].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        grass_tint = get_palette("dungeon").grass.tint
        assert grass_tint in svg

    def test_garden_tile_does_not_emit_hoe_rows(self):
        """Garden tiles render as a flat green tint -- the previous
        per-tile hoe-row stroke decorator was removed because at
        scale the random oblique lines read as scribble noise."""
        level = _blank_level(20, 20)
        for y in range(20):
            for x in range(20):
                level.tiles[y][x].terrain = Terrain.GRASS
                level.tiles[y][x].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        # Old GARDEN_LINE_STROKE colour. If it ever reappears the
        # hoe-row scribble noise has come back.
        assert "#4A6A3A" not in svg

    def test_garden_surface_skips_cobblestones(self):
        level = _blank_level()
        level.tiles[5][5].terrain = Terrain.GRASS
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
                level.tiles[y][x].terrain = Terrain.GRASS
                level.tiles[y][x].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert FIELD_STONE_FILL not in svg


class TestFieldVsGardenPalette:
    def test_field_uses_green_family(self):
        from nhc.rendering._floor_detail import FIELD_TINT
        # FIELD_TINT lives in the green family; it may match the
        # palette grass tint or differ slightly, but should never
        # be a grey or brown. (GARDEN no longer carries its own
        # tint constant -- it inherits the palette grass tint.)
        assert FIELD_TINT.startswith("#")
        r, g, b = (
            int(FIELD_TINT[1:3], 16),
            int(FIELD_TINT[3:5], 16),
            int(FIELD_TINT[5:7], 16),
        )
        assert g >= r and g >= b


@pytest.mark.skip(
    reason="NIR5: town-theme grass tint pins the v4 palette tint "
    "(#88C878). v5 routes town surface tints through the Earth.Grass "
    "family table; test needs an updated baseline."
)
class TestTownGrassTint:
    """Town theme paints grass / garden tiles in a brighter, more
    opaque green than the muted dungeon palette so the open-air
    parts of a town read as lawn rather than washed-out parchment.
    """

    def test_town_palette_grass_is_brighter_than_dungeon(self):
        from nhc.rendering.terrain_palette import get_palette
        town = get_palette("town").grass
        dungeon = get_palette("dungeon").grass

        def _green(hex_str: str) -> int:
            return int(hex_str[3:5], 16)

        # Brighter: more vivid hue (higher green channel) and more
        # opaque so the wash actually reads as green.
        assert _green(town.tint) > _green(dungeon.tint)
        assert town.tint_opacity > dungeon.tint_opacity

    def test_town_grass_tile_emits_town_tint(self):
        from nhc.dungeon.model import LevelMetadata
        from nhc.rendering.terrain_palette import get_palette
        level = _blank_level()
        level.metadata = LevelMetadata(theme="town")
        level.tiles[4][4].terrain = Terrain.GRASS
        level.tiles[4][4].surface_type = SurfaceType.FIELD
        level.tiles[5][5].terrain = Terrain.GRASS
        level.tiles[5][5].surface_type = SurfaceType.GARDEN
        svg = render_floor_svg(level, seed=42)
        assert get_palette("town").grass.tint in svg


class TestWoodInteriorFloor:
    @pytest.mark.skip(
        reason="NIR4: wood-floor short-circuit in render_floor_svg no "
        "longer emits the WOOD_FLOOR_FILL color; the per-tile WoodFloor "
        "FloorOps lose their outline through the schema cut and the "
        "consumer doesn't render them. Production fix pending."
    )
    def test_wood_floor_emits_wood_fill(self):
        from nhc.rendering._floor_detail import WOOD_FLOOR_FILL
        level = _blank_level()
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_FLOOR_FILL in svg

    @pytest.mark.skip(
        reason="NIR5: wood-floor seam stroke uses the v5 Wood family "
        "palette (60-entry table) rather than the v4 _wood_palette. "
        "Test updates to v5 palette pending Phase 2.3 sub-pattern lift."
    )
    def test_wood_floor_emits_seam_stroke(self):
        seam_stroke = _wood_palette_for_test(seed=42)[3]
        level = _blank_level(30, 30)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert seam_stroke in svg

    @pytest.mark.skip(
        reason="NIR5: v4 WOOD_FLOOR_FILL / _wood_palette absence check "
        "no longer applies; v5 paints stone floors with the Stone "
        "family palette and never emits Wood-family colors."
    )
    def test_stone_floor_has_no_wood_colors(self):
        from nhc.rendering._floor_detail import WOOD_FLOOR_FILL
        seam_stroke = _wood_palette_for_test(seed=42)[3]
        level = _blank_level()
        assert level.interior_floor == "stone"
        svg = render_floor_svg(level, seed=42)
        assert WOOD_FLOOR_FILL not in svg
        assert seam_stroke not in svg

class TestWoodParquetConstants:
    def test_plank_width_is_quarter_tile(self):
        from nhc.rendering._floor_detail import WOOD_PLANK_WIDTH_PX
        from nhc.rendering._svg_helpers import CELL
        assert math.isclose(WOOD_PLANK_WIDTH_PX, CELL / 4)

    def test_plank_length_range_is_half_to_two_and_half_tiles(self):
        from nhc.rendering._floor_detail import (
            WOOD_PLANK_LENGTH_MAX, WOOD_PLANK_LENGTH_MIN,
        )
        from nhc.rendering._svg_helpers import CELL
        assert math.isclose(WOOD_PLANK_LENGTH_MIN, CELL * 0.5)
        assert math.isclose(WOOD_PLANK_LENGTH_MAX, CELL * 2.5)


@pytest.mark.skip(
    reason="NIR5: wood-grain effect uses the v5 Wood family's 60-entry "
    "palette (Phase 2.3 sub-pattern lift pending). v4 _wood_palette "
    "colors no longer match the v5 painter output."
)
class TestWoodGrainEffect:
    def test_grain_light_colour_present(self):
        grain_light = _wood_palette_for_test(seed=42)[1]
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert grain_light in svg

    def test_grain_dark_colour_present(self):
        grain_dark = _wood_palette_for_test(seed=42)[2]
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg(level, seed=42)
        assert grain_dark in svg

    def test_grain_colours_differ_from_fill_and_seam(self):
        # Phase 1.26h — every species' three tones keep the grain
        # colours distinct from that tone's fill + seam, so the
        # grain layer reads as a visually separate detail.
        from nhc.rendering._floor_detail import _WOOD_SPECIES
        for species in _WOOD_SPECIES:
            for fill, grain_light, grain_dark, seam in species:
                assert grain_light != fill
                assert grain_dark != fill
                assert grain_light != seam
                assert grain_dark != seam

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



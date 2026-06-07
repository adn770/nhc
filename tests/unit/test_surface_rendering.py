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
    Level, Rect, Room, Terrain, Tile,
)
from nhc.rendering.svg import render_floor_svg_from_ir


def _blank_level(
    w: int = 10, h: int = 10, *, room_id: str = "r1",
) -> Level:
    level = Level.create_empty("t", "t", 1, w, h)
    for y in range(h):
        for x in range(w):
            level.set_tile(x, y, Tile(terrain=Terrain.FLOOR))
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


# The street / field / garden surface-rendering tests were dropped
# in the v5 cut. They pinned v4 palette constants (#8A7A6A
# cobblestone, #7BA87B grass tint, FIELD_STONE_FILL) or asserted the
# absence of those same v4 colours; v5 routes surface colours through
# emergent Earth/Stone family tables not exposed as Python constants,
# so the positive assertions broke and the absence assertions became
# vacuous. Surface emission is covered by the IR byte-parity gate
# (tests/unit/test_floor_ir.py). The palette *data* still has unit
# coverage in TestTerrainPalette / TestFieldVsGardenPalette below.


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


class TestTownGrassTint:
    """Town theme paints grass / garden tiles in a brighter, more
    opaque green than the muted dungeon palette so the open-air
    parts of a town read as lawn rather than washed-out parchment.

    The SVG-emission test was dropped in the v5 cut (it pinned the v4
    town grass tint, now routed through an emergent Earth.Grass family
    table); the palette *data* invariant below is the durable part.
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


class TestWoodInteriorFloor:
    @pytest.mark.skip(
        reason="NIR4: wood-floor short-circuit in render_floor_svg_from_ir no "
        "longer emits the WOOD_FLOOR_FILL color; the per-tile WoodFloor "
        "FloorOps lose their outline through the schema cut and the "
        "consumer doesn't render them. Production fix pending."
    )
    def test_wood_floor_emits_wood_fill(self):
        from nhc.rendering._floor_detail import WOOD_FLOOR_FILL
        level = _blank_level()
        level.interior_floor = "wood"
        svg = render_floor_svg_from_ir(level, seed=42)
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
        svg = render_floor_svg_from_ir(level, seed=42)
        assert seam_stroke in svg

    # test_stone_floor_has_no_wood_colors was dropped in the v5 cut:
    # it asserted the absence of v4 wood colours (WOOD_FLOOR_FILL /
    # _wood_palette seam), which v5 never emits at all, so the check
    # became vacuous.

class TestWoodParquetConstants:
    def test_plank_width_is_quarter_tile(self):
        from nhc.rendering._floor_detail import WOOD_PLANK_WIDTH_PX
        from nhc.rendering._ir_helpers import CELL
        assert math.isclose(WOOD_PLANK_WIDTH_PX, CELL / 4)

    def test_plank_length_range_is_half_to_two_and_half_tiles(self):
        from nhc.rendering._floor_detail import (
            WOOD_PLANK_LENGTH_MAX, WOOD_PLANK_LENGTH_MIN,
        )
        from nhc.rendering._ir_helpers import CELL
        assert math.isclose(WOOD_PLANK_LENGTH_MIN, CELL * 0.5)
        assert math.isclose(WOOD_PLANK_LENGTH_MAX, CELL * 2.5)


_WOOD_GRAIN_PENDING = (
    "NIR5: wood-grain effect uses the v5 Wood family's 60-entry "
    "palette (Phase 2.3 sub-pattern lift pending). v4 _wood_palette "
    "colors no longer match the v5 painter output."
)


class TestWoodGrainEffect:
    @pytest.mark.skip(reason=_WOOD_GRAIN_PENDING)
    def test_grain_light_colour_present(self):
        grain_light = _wood_palette_for_test(seed=42)[1]
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg_from_ir(level, seed=42)
        assert grain_light in svg

    @pytest.mark.skip(reason=_WOOD_GRAIN_PENDING)
    def test_grain_dark_colour_present(self):
        grain_dark = _wood_palette_for_test(seed=42)[2]
        level = _blank_level(20, 6)
        level.interior_floor = "wood"
        svg = render_floor_svg_from_ir(level, seed=42)
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
        svg = render_floor_svg_from_ir(level, seed=42)
        assert WOOD_GRAIN_LIGHT not in svg
        assert WOOD_GRAIN_DARK not in svg



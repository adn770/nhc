"""Tests for rendering theme system."""

from nhc.dungeon.model import Terrain
from nhc.rendering.terminal.glyphs import (
    CORRIDOR_GLYPH,
    TERRAIN_GLYPHS,
    wall_glyph,
)
from nhc.rendering.terminal.themes import (
    THEMES, THEME_BASIC, THEME_EXPERIMENTAL, THEME_MODERN,
    get_theme, set_theme,
)


class TestThemeRegistry:
    def test_three_themes_available(self):
        assert len(THEMES) == 3
        assert "basic" in THEMES
        assert "modern" in THEMES
        assert "experimental" in THEMES

    def test_default_is_modern(self):
        set_theme("modern")
        assert get_theme().name == "modern"

    def test_switch_to_basic(self):
        set_theme("basic")
        theme = get_theme()
        assert theme.name == "basic"
        assert theme.color_depth == "16"
        set_theme("modern")  # reset

    def test_switch_to_experimental(self):
        set_theme("experimental")
        theme = get_theme()
        assert theme.name == "experimental"
        assert theme.color_depth == "256"
        set_theme("modern")  # reset


class TestBasicTheme:
    def test_ascii_walls(self):
        """Basic theme uses | and - for walls, not unicode."""
        theme = THEME_BASIC
        walls = theme.walls
        for key, glyph in walls.items():
            assert glyph in ("|", "-", "+"), \
                f"Basic wall {key} has non-ASCII glyph: {glyph}"

    def test_ascii_box_chars(self):
        theme = THEME_BASIC
        assert theme.box_tl == "+"
        assert theme.box_tr == "+"
        assert theme.box_bl == "+"
        assert theme.box_br == "+"
        assert theme.box_h == "-"
        assert theme.box_v == "|"
        assert theme.h_line == "-"

    def test_16_color_depth(self):
        assert THEME_BASIC.color_depth == "16"

    def test_terrain_uses_ascii(self):
        """Wall glyph should be - not unicode ─."""
        _, glyph_char, _ = THEME_BASIC.terrain[Terrain.WALL]
        assert glyph_char == "white"  # color
        glyph = THEME_BASIC.terrain[Terrain.WALL][0]
        assert glyph == "-"


class TestModernTheme:
    def test_unicode_walls(self):
        theme = THEME_MODERN
        assert theme.walls[(True, True, False, False)] == "│"
        assert theme.walls[(False, False, True, True)] == "─"
        assert theme.walls[(False, True, True, False)] == "┌"

    def test_unicode_box_chars(self):
        theme = THEME_MODERN
        assert theme.box_tl == "╭"
        assert theme.box_br == "╯"
        assert theme.h_line == "─"

    def test_256_color_depth(self):
        assert THEME_MODERN.color_depth == "256"


class TestExperimentalTheme:
    def test_heavy_walls(self):
        theme = THEME_EXPERIMENTAL
        assert theme.walls[(True, True, False, False)] == "┃"
        assert theme.walls[(False, False, True, True)] == "━"
        assert theme.walls[(False, True, True, False)] == "┏"

    def test_graphical_features(self):
        theme = THEME_EXPERIMENTAL
        assert theme.features["stairs_up"] == ("△", "bright_white")
        assert theme.features["stairs_down"] == ("▽", "bright_white")

    def test_no_player_glyph_override(self):
        """Player should always be @ in all themes."""
        assert THEME_EXPERIMENTAL.player_glyph is None
        assert THEME_MODERN.player_glyph is None
        assert THEME_BASIC.player_glyph is None

    def test_floor_is_dot(self):
        assert THEME_EXPERIMENTAL.terrain[Terrain.FLOOR][0] == "."

    def test_boxes_use_rounded(self):
        theme = THEME_EXPERIMENTAL
        assert theme.box_tl == "╭"
        assert theme.box_br == "╯"

    def test_256_color_depth(self):
        assert THEME_EXPERIMENTAL.color_depth == "256"


class TestGlyphsCompat:
    def test_wall_glyph_uses_theme(self):
        set_theme("basic")
        assert wall_glyph(True, True, False, False) == "|"
        set_theme("modern")
        assert wall_glyph(True, True, False, False) == "│"
        set_theme("experimental")
        assert wall_glyph(True, True, False, False) == "┃"
        set_theme("modern")  # reset

    def test_terrain_glyphs_proxy(self):
        set_theme("basic")
        glyph, _, _ = TERRAIN_GLYPHS[Terrain.WALL]
        assert glyph == "-"
        set_theme("modern")
        glyph, _, _ = TERRAIN_GLYPHS[Terrain.WALL]
        assert glyph == "─"
        set_theme("modern")  # reset

    def test_corridor_glyph_proxy(self):
        set_theme("modern")
        assert CORRIDOR_GLYPH[0] == "#"
        set_theme("experimental")
        assert CORRIDOR_GLYPH[0] == "⣿"
        set_theme("modern")  # reset

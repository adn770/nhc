"""Tests for depth-based dungeon theme progression."""

from __future__ import annotations

import pytest

from nhc.dungeon.themes import theme_for_depth
from nhc.dungeon.terrain import THEME_PARAMS


class TestThemeForDepth:
    """theme_for_depth maps depth ranges to themes."""

    @pytest.mark.parametrize("depth,expected", [
        (1, "dungeon"),
        (2, "dungeon"),
        (4, "dungeon"),
        (5, "crypt"),
        (8, "crypt"),
        (9, "cave"),
        (12, "cave"),
        (13, "castle"),
        (16, "castle"),
        (17, "abyss"),
        (20, "abyss"),
        (100, "abyss"),
    ])
    def test_depth_to_theme(self, depth: int, expected: str):
        assert theme_for_depth(depth) == expected

    def test_depth_zero_is_dungeon(self):
        assert theme_for_depth(0) == "dungeon"

    def test_negative_depth_is_dungeon(self):
        assert theme_for_depth(-1) == "dungeon"

    def test_all_returned_themes_have_terrain_params(self):
        """Every theme returned by theme_for_depth must exist
        in THEME_PARAMS so apply_terrain can use it."""
        for depth in range(1, 30):
            theme = theme_for_depth(depth)
            assert theme in THEME_PARAMS, (
                f"depth {depth} → theme {theme!r} not in THEME_PARAMS"
            )

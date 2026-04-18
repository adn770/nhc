"""Tests for underworld floor generation in the game loop."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, Terrain
from nhc.dungeon.pipeline import generate_level
from nhc.hexcrawl.underworld import (
    floor_dimensions,
    theme_for_underworld_depth,
)


class TestUnderworldFloorGeneration:
    def test_floor3_uses_fungal_theme(self):
        """Depth 3 underground floor uses fungal_cavern theme."""
        theme = theme_for_underworld_depth(3)
        w, h = floor_dimensions(3, 3)
        params = GenerationParams(
            width=w, height=h, depth=3,
            shape_variety=0.3, theme=theme, seed=42,
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert level.metadata.theme == "fungal_cavern"

    def test_floor4_uses_lava_theme(self):
        """Depth 4 underground floor uses lava_chamber theme."""
        theme = theme_for_underworld_depth(4)
        w, h = floor_dimensions(4, 4)
        params = GenerationParams(
            width=w, height=h, depth=4,
            shape_variety=0.3, theme=theme, seed=42,
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert level.metadata.theme == "lava_chamber"

    def test_floor5_uses_lake_theme(self):
        """Depth 5 underground floor uses underground_lake theme."""
        theme = theme_for_underworld_depth(5)
        w, h = floor_dimensions(7, 5)
        params = GenerationParams(
            width=w, height=h, depth=5,
            shape_variety=0.3, theme=theme, seed=42,
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert level.metadata.theme == "underground_lake"

    def test_deeper_floors_are_larger(self):
        """Deeper floors in the same cluster should be larger."""
        w2, h2 = floor_dimensions(4, 2)
        w4, h4 = floor_dimensions(4, 4)
        assert w4 > w2
        assert h4 > h2

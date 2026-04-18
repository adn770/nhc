"""Tests for settlement-specific SVG rendering."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.settlement import SettlementGenerator
from nhc.dungeon.model import Level, Terrain
from nhc.rendering.svg import render_floor_svg


def _make_settlement(seed: int = 42) -> Level:
    gen = SettlementGenerator()
    params = GenerationParams(
        width=40, height=30, depth=1, seed=seed,
        template="procedural:settlement",
    )
    return gen.generate(params, rng=random.Random(seed))


class TestSettlementHatching:
    def test_no_hatching_on_settlement(self):
        """Settlement SVGs should not contain cross-hatching."""
        level = _make_settlement()
        svg = render_floor_svg(level, seed=42)
        # Hatching uses a specific group id
        assert "hatch" not in svg.lower() or "hatching" not in svg


class TestStreetRendering:
    def test_streets_exist_in_level(self):
        level = _make_settlement()
        street_count = sum(
            1 for row in level.tiles for t in row if t.is_street
        )
        assert street_count > 0

    def test_street_tiles_are_floor(self):
        level = _make_settlement()
        for row in level.tiles:
            for t in row:
                if t.is_street:
                    assert t.terrain == Terrain.FLOOR

    def test_settlement_svg_renders(self):
        """Settlement SVG should render without errors."""
        level = _make_settlement()
        svg = render_floor_svg(level, seed=42)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_cobblestone_pattern_on_streets(self):
        """Street tiles should have cobblestone rect elements."""
        level = _make_settlement()
        svg = render_floor_svg(level, seed=42)
        # Cobblestone uses a specific stroke color
        assert "#8A7A6A" in svg or "cobble" in svg.lower()

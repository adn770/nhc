"""Tests for mine-specific SVG rendering (cart tracks, ore deposits)."""

from __future__ import annotations

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.dungeon.transforms import add_cart_tracks, add_ore_deposits
from nhc.rendering.svg import render_floor_svg


def _mine_level(seed: int = 42) -> Level:
    params = GenerationParams(
        width=60, height=40, depth=1, seed=seed,
    )
    rng = random.Random(seed)
    level = BSPGenerator().generate(params, rng=rng)
    add_cart_tracks(level, rng)
    add_ore_deposits(level, rng)
    return level


class TestCartTrackRendering:
    def test_track_tiles_render_rails(self):
        level = _mine_level()
        # Confirm transform marked tracks
        assert sum(
            1 for row in level.tiles for t in row
            if t.surface_type == SurfaceType.TRACK
        ) > 0
        svg = render_floor_svg(level)
        # Rail marker (group id) should appear in output
        assert "cart-tracks" in svg

    def test_no_tracks_no_track_group(self):
        """If no tiles are tracks, the SVG skips the rails group."""
        params = GenerationParams(
            width=40, height=25, depth=1, seed=42,
        )
        level = BSPGenerator().generate(params, rng=random.Random(42))
        # Don't apply add_cart_tracks
        svg = render_floor_svg(level)
        assert "cart-tracks" not in svg


class TestOreDepositRendering:
    def test_ore_tiles_render_sparkles(self):
        level = _mine_level()
        assert sum(
            1 for row in level.tiles for t in row
            if t.feature == "ore_deposit"
        ) > 0
        svg = render_floor_svg(level)
        assert "ore-deposits" in svg

    def test_no_ore_no_ore_group(self):
        params = GenerationParams(
            width=40, height=25, depth=1, seed=42,
        )
        level = BSPGenerator().generate(params, rng=random.Random(42))
        svg = render_floor_svg(level)
        assert "ore-deposits" not in svg

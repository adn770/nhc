"""Tests for lava terrain generation via cellular automata."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, SurfaceType, Terrain
from nhc.dungeon.pipeline import generate_level


class TestLavaGeneration:
    def test_lava_chamber_has_lava_tiles(self):
        """lava_chamber theme should produce lava terrain tiles."""
        params = GenerationParams(
            width=80, height=50, depth=1, seed=42,
            theme="lava_chamber",
        )
        level = generate_level(params)
        lava_count = sum(
            1 for row in level.tiles for t in row
            if t.terrain == Terrain.LAVA
        )
        assert lava_count > 0

    def test_dungeon_theme_has_no_lava(self):
        """Standard dungeon theme should not produce lava."""
        params = GenerationParams(
            width=80, height=40, depth=1, seed=42,
            theme="dungeon",
        )
        level = generate_level(params)
        lava_count = sum(
            1 for row in level.tiles for t in row
            if t.terrain == Terrain.LAVA
        )
        assert lava_count == 0

    def test_lava_only_on_room_floors(self):
        """Lava should only replace floor tiles, not corridors."""
        params = GenerationParams(
            width=80, height=50, depth=1, seed=42,
            theme="lava_chamber",
        )
        level = generate_level(params)
        for row in level.tiles:
            for t in row:
                if t.terrain == Terrain.LAVA:
                    assert t.surface_type != SurfaceType.CORRIDOR
                    assert not t.feature

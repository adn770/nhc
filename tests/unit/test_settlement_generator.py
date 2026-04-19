"""Tests for the SettlementGenerator."""

import random

from nhc.dungeon.generators.settlement import (
    DISTRICT_TYPES,
    SIZE_CLASSES,
    SettlementGenerator,
)
from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.model import Level, SurfaceType, Terrain


class TestSizeClasses:
    def test_all_size_classes_defined(self):
        for name in ("hamlet", "village", "town", "city"):
            assert name in SIZE_CLASSES

    def test_size_class_ordering(self):
        """Larger sizes have bigger maps and more buildings."""
        prev_area = 0
        for name in ("hamlet", "village", "town", "city"):
            sc = SIZE_CLASSES[name]
            area = sc["width"] * sc["height"]
            assert area > prev_area
            prev_area = area


class TestDistrictTypes:
    def test_district_types_exist(self):
        assert len(DISTRICT_TYPES) >= 5
        assert "market" in DISTRICT_TYPES
        assert "residential" in DISTRICT_TYPES
        assert "temple" in DISTRICT_TYPES


class TestSettlementGenerator:
    def test_generates_village(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=40, height=30, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3
        assert level.metadata.theme == "settlement"

    def test_generates_city(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=80, height=50, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        assert isinstance(level, Level)
        assert len(level.rooms) >= 8

    def test_has_streets(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        street_tiles = sum(
            1 for row in level.tiles for t in row
            if t.surface_type == SurfaceType.STREET
        )
        assert street_tiles > 0

    def test_streets_are_floor(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        for row in level.tiles:
            for t in row:
                if t.surface_type == SurfaceType.STREET:
                    assert t.terrain == Terrain.FLOOR

    def test_rooms_have_district_tags(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        tagged = [
            r for r in level.rooms
            if any(t in DISTRICT_TYPES for t in r.tags)
        ]
        assert len(tagged) > 0

    def test_has_entry_stairs(self):
        gen = SettlementGenerator()
        params = GenerationParams(
            width=40, height=30, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        stairs = sum(
            1 for row in level.tiles for t in row
            if t.feature == "stairs_up"
        )
        assert stairs >= 1

    def test_city_has_walls(self):
        """City-sized settlements should have outer walls."""
        gen = SettlementGenerator()
        params = GenerationParams(
            width=80, height=50, depth=1, seed=42,
            template="procedural:settlement",
        )
        level = gen.generate(params, rng=random.Random(42))
        # Perimeter should be mostly walls
        perimeter_walls = 0
        perimeter_total = 0
        for x in range(level.width):
            perimeter_total += 2
            if level.tiles[0][x].terrain == Terrain.WALL:
                perimeter_walls += 1
            if level.tiles[level.height - 1][x].terrain == Terrain.WALL:
                perimeter_walls += 1
        for y in range(1, level.height - 1):
            perimeter_total += 2
            if level.tiles[y][0].terrain == Terrain.WALL:
                perimeter_walls += 1
            if level.tiles[y][level.width - 1].terrain == Terrain.WALL:
                perimeter_walls += 1
        assert perimeter_walls / perimeter_total > 0.7

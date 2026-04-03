"""Tests for the cellular automata cave generator."""

from __future__ import annotations

import random
from collections import deque

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.cellular import CellularGenerator
from nhc.dungeon.model import Terrain
from nhc.dungeon.populator import populate_level
from nhc.dungeon.room_types import assign_room_types
from nhc.dungeon.terrain import apply_terrain


def _generate(seed: int = 42, depth: int = 1, **kw) -> "Level":
    rng = random.Random(seed)
    params = GenerationParams(depth=depth, theme="cave", **kw)
    gen = CellularGenerator()
    return gen.generate(params, rng=rng)


def _flood_reachable(level, start_x, start_y):
    """BFS flood fill returning all reachable floor tiles."""
    walkable = {Terrain.FLOOR, Terrain.WATER, Terrain.GRASS}
    visited = set()
    queue = deque([(start_x, start_y)])
    while queue:
        x, y = queue.popleft()
        if (x, y) in visited:
            continue
        if not level.in_bounds(x, y):
            continue
        if level.tiles[y][x].terrain not in walkable:
            continue
        visited.add((x, y))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            queue.append((x + dx, y + dy))
    return visited


class TestCellularGenerator:
    """Basic cave generation properties."""

    def test_generates_level(self):
        level = _generate()
        assert level.width == 120
        assert level.height == 40
        assert level.depth == 1

    def test_has_rooms(self):
        level = _generate()
        assert len(level.rooms) >= 1

    def test_has_stairs_up(self):
        level = _generate()
        found = any(
            level.tiles[y][x].feature == "stairs_up"
            for y in range(level.height)
            for x in range(level.width)
        )
        assert found

    def test_has_stairs_down(self):
        level = _generate()
        found = any(
            level.tiles[y][x].feature == "stairs_down"
            for y in range(level.height)
            for x in range(level.width)
        )
        assert found

    def test_entry_room_tagged(self):
        level = _generate()
        entry_rooms = [r for r in level.rooms if "entry" in r.tags]
        assert len(entry_rooms) >= 1

    def test_exit_room_tagged(self):
        level = _generate()
        exit_rooms = [r for r in level.rooms if "exit" in r.tags]
        assert len(exit_rooms) >= 1

    def test_has_floor_tiles(self):
        level = _generate()
        floor_count = sum(
            1 for row in level.tiles for t in row
            if t.terrain == Terrain.FLOOR
        )
        # Should have a substantial number of floor tiles
        assert floor_count > 100

    def test_border_no_floor(self):
        level = _generate()
        for x in range(level.width):
            assert level.tiles[0][x].terrain != Terrain.FLOOR
            assert level.tiles[level.height - 1][x].terrain != Terrain.FLOOR
        for y in range(level.height):
            assert level.tiles[y][0].terrain != Terrain.FLOOR
            assert level.tiles[y][level.width - 1].terrain != Terrain.FLOOR

    def test_deterministic(self):
        level1 = _generate(seed=99999)
        level2 = _generate(seed=99999)
        for y in range(level1.height):
            for x in range(level1.width):
                assert (level1.tiles[y][x].terrain
                        == level2.tiles[y][x].terrain)

    def test_all_floor_reachable_from_stairs_up(self):
        level = _generate()
        # Find stairs_up
        start = None
        for y in range(level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature == "stairs_up":
                    start = (x, y)
                    break
            if start:
                break
        assert start is not None

        reachable = _flood_reachable(level, *start)

        # All non-corridor floor tiles should be reachable
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.terrain == Terrain.FLOOR:
                    assert (x, y) in reachable, (
                        f"Floor tile ({x},{y}) not reachable from stairs"
                    )

    def test_has_walls(self):
        level = _generate()
        wall_count = sum(
            1 for row in level.tiles for t in row
            if t.terrain == Terrain.WALL
        )
        assert wall_count > 0

    def test_metadata_theme(self):
        level = _generate()
        assert level.metadata.theme == "cave"

    def test_different_seeds_different_levels(self):
        level1 = _generate(seed=1)
        level2 = _generate(seed=2)
        rooms1 = len(level1.rooms)
        rooms2 = len(level2.rooms)
        tiles1 = sum(1 for row in level1.tiles for t in row
                     if t.terrain == Terrain.FLOOR)
        tiles2 = sum(1 for row in level2.tiles for t in row
                     if t.terrain == Terrain.FLOOR)
        # At least one of rooms or floor count should differ
        assert rooms1 != rooms2 or tiles1 != tiles2


class TestCellularGeneratorIntegration:
    """Cave levels work with the downstream pipeline."""

    def test_assign_room_types(self):
        level = _generate()
        rng = random.Random(42)
        assign_room_types(level, rng)
        # Should not raise

    def test_populate_level(self):
        level = _generate()
        rng = random.Random(42)
        populate_level(level, rng=rng)
        assert len(level.entities) > 0

    def test_apply_terrain(self):
        level = _generate()
        rng = random.Random(42)
        apply_terrain(level, rng)
        # Should not raise

    def test_full_pipeline(self):
        level = _generate(seed=123, depth=3)
        rng = random.Random(456)
        assign_room_types(level, rng)
        apply_terrain(level, rng)
        populate_level(level, rng=rng)
        assert len(level.rooms) >= 1
        assert len(level.entities) > 0

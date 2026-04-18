"""Tests for the walled (keep) layout strategy and transforms."""

import random

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators._layout import LAYOUT_STRATEGIES, plan_walled
from nhc.dungeon.model import Level, Rect, Terrain
from nhc.dungeon.pipeline import generate_level
from nhc.dungeon.transforms import add_battlements, add_gate


def _sample_interior_rects() -> list[Rect]:
    """Rooms arranged inside a keep interior."""
    return [
        Rect(15, 12, 8, 8),    # center (courtyard candidate)
        Rect(6, 6, 5, 5),      # top-left
        Rect(28, 6, 5, 5),     # top-right
        Rect(6, 22, 5, 5),     # bottom-left
        Rect(28, 22, 5, 5),    # bottom-right
        Rect(16, 5, 6, 5),     # top-center (gate candidate)
    ]


class TestPlanWalled:
    def test_registered(self):
        assert "walled" in LAYOUT_STRATEGIES

    def test_all_rooms_reachable(self):
        rects = _sample_interior_rects()
        pairs, entrance, exit_idx = plan_walled(rects, 0.8, random.Random(42))
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for a, b in pairs:
            adj[a].add(b)
            adj[b].add(a)
        visited = set()
        stack = [entrance]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj[n])
        assert visited == set(range(len(rects)))

    def test_courtyard_is_largest_room(self):
        rects = _sample_interior_rects()
        pairs, entrance, exit_idx = plan_walled(rects, 0.8, random.Random(42))
        # The courtyard (hub) should be the entrance — largest room
        largest = max(
            range(len(rects)),
            key=lambda i: rects[i].width * rects[i].height,
        )
        assert entrance == largest


class TestAddBattlements:
    def test_creates_outer_wall_ring(self):
        params = GenerationParams(
            width=50, height=35, depth=1, seed=42,
        )
        rng = random.Random(42)
        from nhc.dungeon.generators.bsp import BSPGenerator
        level = BSPGenerator().generate(params, rng=rng)
        add_battlements(level, random.Random(42))
        # Top and bottom rows should have wall tiles
        top_walls = sum(
            1 for x in range(level.width)
            if level.tiles[0][x].terrain == Terrain.WALL
        )
        bottom_walls = sum(
            1 for x in range(level.width)
            if level.tiles[level.height - 1][x].terrain == Terrain.WALL
        )
        assert top_walls > level.width * 0.8
        assert bottom_walls > level.width * 0.8

    def test_battlements_two_tiles_thick(self):
        params = GenerationParams(
            width=50, height=35, depth=1, seed=42,
        )
        rng = random.Random(42)
        from nhc.dungeon.generators.bsp import BSPGenerator
        level = BSPGenerator().generate(params, rng=rng)
        add_battlements(level, random.Random(42))
        # Second row should also be mostly walls
        row1_walls = sum(
            1 for x in range(level.width)
            if level.tiles[1][x].terrain == Terrain.WALL
        )
        assert row1_walls > level.width * 0.7


class TestAddGate:
    def test_creates_gate_opening(self):
        params = GenerationParams(
            width=50, height=35, depth=1, seed=42,
        )
        rng = random.Random(42)
        from nhc.dungeon.generators.bsp import BSPGenerator
        level = BSPGenerator().generate(params, rng=rng)
        add_battlements(level, random.Random(42))
        add_gate(level, random.Random(42))
        # There should be at least one door in the outer wall area
        gate_doors = 0
        for y in range(3):
            for x in range(level.width):
                if level.tiles[y][x].feature and "door" in level.tiles[y][x].feature:
                    gate_doors += 1
        for y in range(level.height - 3, level.height):
            for x in range(level.width):
                if level.tiles[y][x].feature and "door" in level.tiles[y][x].feature:
                    gate_doors += 1
        for y in range(level.height):
            for x in range(3):
                if level.tiles[y][x].feature and "door" in level.tiles[y][x].feature:
                    gate_doors += 1
            for x in range(level.width - 3, level.width):
                if level.tiles[y][x].feature and "door" in level.tiles[y][x].feature:
                    gate_doors += 1
        assert gate_doors >= 1


class TestKeepPipeline:
    def test_keep_template_generates_valid_level(self):
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:keep",
        )
        level = generate_level(params)
        assert isinstance(level, Level)
        assert len(level.rooms) >= 3

    def test_keep_has_outer_walls(self):
        params = GenerationParams(
            width=60, height=40, depth=1, seed=42,
            template="procedural:keep",
        )
        level = generate_level(params)
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
        assert perimeter_walls / perimeter_total > 0.8

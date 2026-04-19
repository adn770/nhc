"""Tests for the cellular automata cave generator."""

from __future__ import annotations

import random
from collections import deque

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.cellular import (
    CellularGenerator, _absorb_corridors_into_caves,
    _erode_wall_peninsulas,
)
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile
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


class TestCellularCorridorShape:
    """Corridors connecting cave regions should not contain long
    unbroken straight runs — caves read as organic when corridors
    are kinked or short."""

    # A single corridor leg is bounded by cellular.MAX_STRAIGHT (4)
    # and the post-process jog breaks runs longer than that, but
    # when every candidate pivot's 3-cell detour is already blocked
    # by neighbouring corridors or cave floor, a run can survive a
    # bit longer.  We allow up to 10 tiles here; previous generator
    # output was 30+ tiles, so this is still a 3×+ improvement.
    MAX_STRAIGHT_RUN = 10

    @staticmethod
    def _longest_straight_run(level) -> int:
        """Return the length of the longest contiguous axis-aligned
        run of corridor tiles in either dimension."""
        w, h = level.width, level.height
        best = 0
        # Horizontal runs
        for y in range(h):
            run = 0
            for x in range(w):
                if (level.tiles[y][x].surface_type
                        == SurfaceType.CORRIDOR):
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
        # Vertical runs
        for x in range(w):
            run = 0
            for y in range(h):
                if (level.tiles[y][x].surface_type
                        == SurfaceType.CORRIDOR):
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
        return best

    def test_no_long_straight_runs_single_seed(self):
        """On a representative seed, no corridor forms a straight
        run longer than MAX_STRAIGHT_RUN tiles."""
        level = _generate(seed=2057302072)
        longest = self._longest_straight_run(level)
        assert longest <= self.MAX_STRAIGHT_RUN, (
            f"Longest straight corridor run = {longest} tiles, "
            f"exceeds limit of {self.MAX_STRAIGHT_RUN}"
        )

    def test_no_long_straight_runs_many_seeds(self):
        """Across many seeds, long straight corridor runs should
        be rare.  Accept occasional outliers but fail if the
        average longest run exceeds the limit."""
        longest_runs = []
        for seed in range(20):
            level = _generate(seed=seed)
            longest_runs.append(self._longest_straight_run(level))
        avg = sum(longest_runs) / len(longest_runs)
        assert avg <= self.MAX_STRAIGHT_RUN, (
            f"Average longest straight run across 20 seeds = "
            f"{avg:.1f}, exceeds limit of {self.MAX_STRAIGHT_RUN}"
        )
        # And at most 20% of seeds may exceed the limit by a lot
        outliers = sum(
            1 for r in longest_runs
            if r > self.MAX_STRAIGHT_RUN + 2
        )
        assert outliers <= len(longest_runs) // 5, (
            f"{outliers} seeds produced corridor runs > "
            f"{self.MAX_STRAIGHT_RUN + 2} tiles; expected ≤ "
            f"{len(longest_runs) // 5}"
        )


class TestErodeWallPeninsulas:
    """Post-processing pass that removes narrow wall protrusions
    from cave regions to prevent knots in the SVG outline."""

    def _make_level_with_peninsula(self) -> Level:
        """Create a level with a single-tile wall peninsula.

        Layout (10x10, floor from rows 1-6, cols 1-8):
            ..........
            .FFFFFFFF.
            .FFFFFFFF.
            .FFF#FFFF.   <- wall peninsula at (4,3)
            .FFFFFFFF.
            .FFFFFFFF.
            .FFFFFFFF.
            ..........

        The wall at (4,3) has floor on all 4 cardinal sides,
        so it's a peninsula tip that should be eroded.
        """
        level = Level.create_empty(
            "test", "Test", depth=1, width=10, height=10,
        )
        # Carve floor
        floor_tiles: set[tuple[int, int]] = set()
        for y in range(1, 7):
            for x in range(1, 9):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
                floor_tiles.add((x, y))
        # Insert single-tile wall peninsula
        level.tiles[3][4] = Tile(terrain=Terrain.WALL)
        floor_tiles.discard((4, 3))
        return level, floor_tiles

    def test_peninsula_tip_removed(self):
        """A 2-wide wall peninsula surrounded by floor on 3 sides
        should be eroded to floor."""
        level, floor_tiles = self._make_level_with_peninsula()
        converted = _erode_wall_peninsulas(level, floor_tiles)
        assert converted > 0, "Should convert some wall tiles"
        # The peninsula tile should now be floor
        assert level.tiles[3][4].terrain == Terrain.FLOOR, (
            "Peninsula tile (4,3) should be floor"
        )

    def test_border_walls_preserved(self):
        """Walls on the map border should never be eroded."""
        level, floor_tiles = self._make_level_with_peninsula()
        _erode_wall_peninsulas(level, floor_tiles)
        # Top row should still be VOID (border)
        for x in range(10):
            assert level.tiles[0][x].terrain != Terrain.FLOOR

    def test_solid_walls_preserved(self):
        """A wall with only 1-2 floor neighbors (part of a solid
        wall mass) should not be eroded."""
        level = Level.create_empty(
            "test", "Test", depth=1, width=10, height=10,
        )
        floor_tiles: set[tuple[int, int]] = set()
        # Floor only on bottom half
        for y in range(5, 9):
            for x in range(1, 9):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
                floor_tiles.add((x, y))
        # Wall row at y=4 borders floor only on south side
        for x in range(1, 9):
            level.tiles[4][x] = Tile(terrain=Terrain.WALL)
        converted = _erode_wall_peninsulas(level, floor_tiles)
        # These wall tiles have floor on only 1 side — keep them
        assert converted == 0, (
            "Solid wall row should not be eroded"
        )

    def test_no_peninsulas_in_generated_cave(self):
        """After full generation, no wall tile should have floor
        on 3+ cardinal sides or on opposite cardinal sides (those
        are the peninsulas/thin walls that cause knots)."""
        level = _generate(seed=42)
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                t = level.tiles[y][x]
                if t.terrain != Terrain.WALL:
                    continue
                n = level.tiles[y-1][x].terrain == Terrain.FLOOR
                s = level.tiles[y+1][x].terrain == Terrain.FLOOR
                e = level.tiles[y][x+1].terrain == Terrain.FLOOR
                w = level.tiles[y][x-1].terrain == Terrain.FLOOR
                card = n + s + e + w
                assert card < 3, (
                    f"Wall peninsula at ({x},{y}) has "
                    f"{card} cardinal floor neighbors"
                )
                if card == 2:
                    assert not (n and s or e and w), (
                        f"Thin wall at ({x},{y}): floor on "
                        f"opposite sides"
                    )


class TestAbsorbCorridorsIntoCaves:
    """Corridor tiles adjacent to cave rooms should be absorbed."""

    def test_no_corridor_tiles_in_generated_cave(self):
        """After full generation, no corridor tile should remain
        adjacent to a cave room — they should all be absorbed."""
        level = _generate(seed=42)
        from nhc.dungeon.generators.cellular import CaveShape
        cave_floor: set[tuple[int, int]] = set()
        for room in level.rooms:
            if isinstance(room.shape, CaveShape):
                cave_floor |= room.floor_tiles()
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                t = level.tiles[y][x]
                if t.surface_type != SurfaceType.CORRIDOR:
                    continue
                # Check if adjacent to a cave room tile
                adjacent = any(
                    (x + dx, y + dy) in cave_floor
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                )
                assert not adjacent, (
                    f"Corridor tile ({x},{y}) is adjacent to "
                    f"cave room but was not absorbed"
                )


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

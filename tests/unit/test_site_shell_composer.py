"""Tests for ``nhc/sites/_shell.py``.

``compose_shell()`` centralizes the perimeter-wall stamping that
was previously inlined in every ``_build_*_floor()``. M1 is a
pure refactor: the same 8-neighbour rule, extracted. These tests
pin the contract so the refactor stays byte-identical.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, Rect, RectShape, Terrain, Tile,
)
from nhc.sites._shell import compose_shell


def _empty_level(w: int, h: int) -> Level:
    return Level.create_empty("lvl", "lvl", 1, w, h)


def _stamp_footprint_as_floor(
    level: Level, footprint: set[tuple[int, int]],
) -> None:
    for (x, y) in footprint:
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)


def _expected_wall_tiles(
    level: Level, footprint: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Replicate the old inline 8-neighbour rule for comparison."""
    out: set[tuple[int, int]] = set()
    for (x, y) in footprint:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = x + dx, y + dy
                if (nx, ny) in footprint:
                    continue
                if not level.in_bounds(nx, ny):
                    continue
                if level.tiles[ny][nx].terrain == Terrain.VOID:
                    out.add((nx, ny))
    return out


class TestComposeShellPerimeter:
    def test_rect_footprint_8_neighbour_ring(self):
        rect = Rect(2, 2, 5, 4)
        shape = RectShape()
        footprint = shape.floor_tiles(rect)
        level = _empty_level(rect.x + rect.width + 2,
                             rect.y + rect.height + 2)
        _stamp_footprint_as_floor(level, footprint)

        expected = _expected_wall_tiles(level, footprint)
        compose_shell(level, {"b0": footprint})

        walls = {
            (x, y)
            for y in range(level.height)
            for x in range(level.width)
            if level.tiles[y][x].terrain is Terrain.WALL
        }
        assert walls == expected

    def test_footprint_tiles_stay_floor(self):
        rect = Rect(1, 1, 6, 5)
        footprint = RectShape().floor_tiles(rect)
        level = _empty_level(rect.x + rect.width + 2,
                             rect.y + rect.height + 2)
        _stamp_footprint_as_floor(level, footprint)

        compose_shell(level, {"b0": footprint})
        for (x, y) in footprint:
            assert level.tiles[y][x].terrain is Terrain.FLOOR

    def test_non_void_tiles_are_preserved(self):
        """Shell must not overwrite a non-VOID tile (future: shared
        walls, already-stamped surface features, etc.)."""
        rect = Rect(1, 1, 4, 4)
        footprint = RectShape().floor_tiles(rect)
        level = _empty_level(rect.x + rect.width + 2,
                             rect.y + rect.height + 2)
        _stamp_footprint_as_floor(level, footprint)

        # Pre-stamp one 8-neighbour as FLOOR; compose_shell must leave it.
        px, py = rect.x - 1, rect.y
        level.tiles[py][px] = Tile(terrain=Terrain.FLOOR)

        compose_shell(level, {"b0": footprint})
        assert level.tiles[py][px].terrain is Terrain.FLOOR

    def test_out_of_bounds_neighbours_skipped(self):
        # Footprint butts up against the level boundary.
        level = _empty_level(6, 6)
        rect = Rect(0, 0, 3, 3)
        footprint = RectShape().floor_tiles(rect)
        _stamp_footprint_as_floor(level, footprint)

        compose_shell(level, {"b0": footprint})
        # No crash; walls stamped only in-bounds.
        walls = {
            (x, y)
            for y in range(level.height)
            for x in range(level.width)
            if level.tiles[y][x].terrain is Terrain.WALL
        }
        for (x, y) in walls:
            assert 0 <= x < level.width
            assert 0 <= y < level.height

    def test_circle_shape_matches_inline_rule(self):
        rect = Rect(1, 1, 9, 9)
        footprint = CircleShape().floor_tiles(rect)
        level = _empty_level(rect.x + rect.width + 2,
                             rect.y + rect.height + 2)
        _stamp_footprint_as_floor(level, footprint)

        expected = _expected_wall_tiles(level, footprint)
        compose_shell(level, {"b0": footprint})
        walls = {
            (x, y)
            for y in range(level.height)
            for x in range(level.width)
            if level.tiles[y][x].terrain is Terrain.WALL
        }
        assert walls == expected

    def test_octagon_shape_matches_inline_rule(self):
        rect = Rect(1, 1, 9, 9)
        footprint = OctagonShape().floor_tiles(rect)
        level = _empty_level(rect.x + rect.width + 2,
                             rect.y + rect.height + 2)
        _stamp_footprint_as_floor(level, footprint)

        expected = _expected_wall_tiles(level, footprint)
        compose_shell(level, {"b0": footprint})
        walls = {
            (x, y)
            for y in range(level.height)
            for x in range(level.width)
            if level.tiles[y][x].terrain is Terrain.WALL
        }
        assert walls == expected

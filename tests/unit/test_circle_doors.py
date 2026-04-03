"""Tests for door placement on circular and hybrid rooms.

Doors on circles must only be placed at the 4 cardinal wall
positions (N, S, E, W from center). Doors on hybrids must be
on the straight rect side or at cardinal points of the arc side,
never on diagonal transition walls.
"""

from __future__ import annotations

import random

import pytest

from nhc.dungeon.generator import GenerationParams
from nhc.dungeon.generators.bsp import BSPGenerator
from nhc.dungeon.model import (
    CircleShape,
    HybridShape,
    Level,
    Rect,
    RectShape,
    Room,
    Terrain,
    Tile,
)


def _generate(seed: int, **kw) -> Level:
    rng = random.Random(seed)
    params = GenerationParams(depth=1, **kw)
    gen = BSPGenerator()
    return gen.generate(params, rng=rng)


def _find_doors(level: Level) -> list[tuple[int, int, str]]:
    """Return all (x, y, feature) door tiles."""
    doors = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tile_at(x, y)
            if tile and tile.feature and "door" in tile.feature:
                doors.append((x, y, tile.feature))
    return doors


def _room_for_door(level: Level, dx: int, dy: int) -> Room | None:
    """Find which room a door at (dx, dy) is adjacent to."""
    for room in level.rooms:
        floor = room.floor_tiles()
        for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (dx + ddx, dy + ddy) in floor:
                return room
    return None


class TestCircleRoomDoors:
    """Doors on circle rooms must be at cardinal positions only."""

    def test_circle_doors_at_cardinal_points(self):
        """All doors adjacent to a circle room must be at one of
        the 4 cardinal wall positions (N/S/E/W from center)."""
        # Generate many levels to find circles with doors
        violations = []
        for seed in range(50):
            level = _generate(seed, shape_variety=0.8)
            doors = _find_doors(level)
            for dx, dy, feat in doors:
                room = _room_for_door(level, dx, dy)
                if room is None:
                    continue
                if not isinstance(room.shape, CircleShape):
                    continue
                # Door must be at a cardinal wall position
                cardinals = room.shape.cardinal_walls(room.rect)
                if (dx, dy) not in cardinals:
                    violations.append((seed, dx, dy, room.id, cardinals))

        assert not violations, (
            f"{len(violations)} doors on non-cardinal circle walls: "
            f"{violations[:5]}"
        )

    def test_circle_has_walls_around_it(self):
        """A circle room should have WALL tiles around its floor."""
        for seed in range(30):
            level = _generate(seed, shape_variety=0.8)
            for room in level.rooms:
                if not isinstance(room.shape, CircleShape):
                    continue
                floor = room.floor_tiles()
                # Check that non-floor neighbors are WALL (not VOID)
                for fx, fy in floor:
                    for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = fx + ddx, fy + ddy
                        if (nx, ny) in floor:
                            continue
                        tile = level.tile_at(nx, ny)
                        if tile and tile.terrain == Terrain.VOID:
                            # Adjacent VOID means missing wall
                            pytest.fail(
                                f"Seed {seed}: circle {room.id} "
                                f"floor ({fx},{fy}) has VOID neighbor "
                                f"({nx},{ny})"
                            )


class TestHybridRoomDoors:
    """Doors on hybrid rooms must not be on diagonal walls."""

    def test_hybrid_doors_not_on_diagonal(self):
        """Doors adjacent to a hybrid room must be on the straight
        rect side or at cardinal points of the arc side."""
        violations = []
        for seed in range(50):
            level = _generate(seed, shape_variety=0.8)
            doors = _find_doors(level)
            for dx, dy, feat in doors:
                room = _room_for_door(level, dx, dy)
                if room is None:
                    continue
                if not isinstance(room.shape, HybridShape):
                    continue
                # Door must be on a straight wall segment:
                # - On the rect half's perimeter (axis-aligned)
                # - Or at a cardinal wall of the circle half
                r = room.rect
                on_rect_edge = (
                    dx == r.x - 1 or dx == r.x2
                    or dy == r.y - 1 or dy == r.y2
                )
                if on_rect_edge:
                    continue
                # Check if it's at a cardinal wall of the circle
                circle_sub = None
                for sub in (room.shape.left, room.shape.right):
                    if isinstance(sub, CircleShape):
                        circle_sub = sub
                        break
                if circle_sub:
                    cardinals = circle_sub.cardinal_walls(room.rect)
                    if (dx, dy) in cardinals:
                        continue
                violations.append((seed, dx, dy, room.id))

        assert not violations, (
            f"{len(violations)} doors on diagonal hybrid walls: "
            f"{violations[:5]}"
        )


class TestCircleDiameterFitsRect:
    """Circle diameter must not exceed the bounding rect."""

    def test_floor_tiles_within_rect(self):
        """No circle floor tile should be outside its bounding rect."""
        for seed in range(50):
            level = _generate(seed, shape_variety=0.8)
            for room in level.rooms:
                if not isinstance(room.shape, CircleShape):
                    continue
                r = room.rect
                for x, y in room.floor_tiles():
                    assert r.x <= x < r.x2 and r.y <= y < r.y2, (
                        f"Seed {seed}: {room.id} floor ({x},{y}) "
                        f"outside rect ({r.x},{r.y},{r.width},{r.height})"
                    )

    def test_diameter_fits_min_dimension(self):
        """Diameter should be <= min(width, height) of the rect."""
        for w, h in [(4, 4), (5, 5), (6, 6), (7, 7), (8, 8),
                     (5, 7), (7, 5), (4, 6), (6, 4)]:
            rect = Rect(0, 0, w, h)
            d = CircleShape._diameter(rect)
            assert d <= min(w, h), (
                f"Rect {w}x{h}: diameter {d} > min({w},{h})"
            )
            assert d % 2 == 1, f"Rect {w}x{h}: diameter {d} not odd"


class TestCircleCardinalWalls:
    """cardinal_walls returns usable positions."""

    def test_cardinal_walls_within_level_bounds(self):
        """Cardinal wall positions must be within level bounds."""
        for seed in range(30):
            level = _generate(seed, shape_variety=0.8)
            for room in level.rooms:
                if not isinstance(room.shape, CircleShape):
                    continue
                cardinals = room.shape.cardinal_walls(room.rect)
                for wx, wy in cardinals:
                    assert level.in_bounds(wx, wy), (
                        f"Seed {seed}: {room.id} cardinal ({wx},{wy}) "
                        f"out of bounds"
                    )

    def test_circle_connected_via_corridors(self):
        """Every circle room should be reachable (connected by at
        least one corridor or adjacent room)."""
        for seed in range(30):
            level = _generate(seed, shape_variety=0.8)
            for room in level.rooms:
                if not isinstance(room.shape, CircleShape):
                    continue
                floor = room.floor_tiles()
                # Check that at least one floor tile has a
                # non-room neighbor that is also FLOOR or a door
                connected = False
                for fx, fy in floor:
                    for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = fx + ddx, fy + ddy
                        if (nx, ny) in floor:
                            continue
                        tile = level.tile_at(nx, ny)
                        if tile and (
                            tile.terrain == Terrain.FLOOR
                            or (tile.feature and "door" in tile.feature)
                        ):
                            connected = True
                            break
                    if connected:
                        break
                assert connected, (
                    f"Seed {seed}: circle {room.id} is disconnected"
                )

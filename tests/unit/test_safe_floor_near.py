"""Tests for :func:`safe_floor_near`.

See ``design/building_interiors.md`` — room centers can land on
an interior wall or a door after multi-room partitioners wire
into town buildings. ``safe_floor_near`` BFS-searches outward
from ``(cx, cy)`` for the first walkable, feature-free tile
inside the room's floor set.
"""

from __future__ import annotations

from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, Terrain, Tile,
)
from nhc.sites._placement import safe_floor_near


def _make_level(
    rect: Rect, walls: set[tuple[int, int]] = frozenset(),
    doors: set[tuple[int, int]] = frozenset(),
) -> tuple[Level, Room]:
    level = Level.create_empty(
        "lvl", "lvl", 1,
        rect.x + rect.width + 2, rect.y + rect.height + 2,
    )
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for (x, y) in walls:
        level.tiles[y][x] = Tile(terrain=Terrain.WALL)
    for (x, y) in doors:
        level.tiles[y][x].feature = "door_closed"
    room = Room(
        id="r", rect=rect, shape=RectShape(), tags=[],
    )
    return level, room


class TestSafeFloorNear:
    def test_returns_center_when_walkable(self):
        level, room = _make_level(Rect(1, 1, 5, 5))
        x, y = safe_floor_near(level, 3, 3, room)
        assert (x, y) == (3, 3)

    def test_shifts_off_wall_at_center(self):
        """A wall smack at the room center forces the picker to
        pick an adjacent FLOOR tile."""
        level, room = _make_level(
            Rect(1, 1, 5, 5), walls={(3, 3)},
        )
        x, y = safe_floor_near(level, 3, 3, room)
        assert (x, y) != (3, 3)
        assert level.tiles[y][x].terrain is Terrain.FLOOR
        assert level.tiles[y][x].feature is None

    def test_shifts_off_door_at_center(self):
        level, room = _make_level(
            Rect(1, 1, 5, 5), doors={(3, 3)},
        )
        x, y = safe_floor_near(level, 3, 3, room)
        assert (x, y) != (3, 3)
        assert level.tiles[y][x].feature is None

    def test_picks_tile_inside_room_floor(self):
        """The picked tile must be inside the room's floor set even
        when the level has walkable tiles outside the room."""
        level, room = _make_level(
            Rect(1, 1, 5, 5), walls={(3, 3)},
        )
        # Add another walkable tile outside the room's rect.
        for y in range(0, level.height):
            for x in range(0, level.width):
                if (x, y) == (0, 0):
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        x, y = safe_floor_near(level, 3, 3, room)
        assert (x, y) in room.floor_tiles()

    def test_falls_back_to_any_floor_when_room_empty(self):
        """When every tile in the room is occupied, the picker
        falls back to any walkable tile on the level."""
        rect = Rect(1, 1, 3, 3)
        walls = {
            (x, y) for x in range(rect.x, rect.x2)
            for y in range(rect.y, rect.y2)
        }
        level, room = _make_level(rect, walls=walls)
        # Mark one tile elsewhere walkable.
        level.tiles[0][0] = Tile(terrain=Terrain.FLOOR)
        x, y = safe_floor_near(level, 2, 2, room)
        assert (x, y) == (0, 0)

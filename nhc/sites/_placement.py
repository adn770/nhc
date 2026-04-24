"""Safe NPC placement helpers for site assemblers.

See ``design/building_interiors.md`` — room centers can land on
an interior wall or a door after M14 wires real partitioners
into town buildings. :func:`safe_floor_near` sidesteps that by
BFS-searching for the nearest walkable feature-free tile.
"""

from __future__ import annotations

from nhc.dungeon.building import Building
from nhc.dungeon.model import Level, Room, Terrain


def safe_floor_near(
    level: Level, cx: int, cy: int, room: Room,
) -> tuple[int, int]:
    """Return a walkable, feature-free tile near ``(cx, cy)``.

    1. If ``(cx, cy)`` is already FLOOR with no feature, return it.
    2. Otherwise BFS outward by Manhattan distance; first FLOOR +
       no-feature tile inside the ``room.floor_tiles()`` set wins.
    3. Fallback: any FLOOR + no-feature tile on the level.
    Raises ``RuntimeError`` when nothing usable is found — every
    building ground floor should always have at least one walkable
    tile, so an exception surfaces a real bug.
    """
    def usable(x: int, y: int) -> bool:
        if not level.in_bounds(x, y):
            return False
        tile = level.tiles[y][x]
        return (
            tile.terrain is Terrain.FLOOR and tile.feature is None
        )

    if usable(cx, cy):
        return (cx, cy)

    room_tiles = room.floor_tiles()
    seen: set[tuple[int, int]] = {(cx, cy)}
    frontier: list[tuple[int, int]] = [(cx, cy)]
    while frontier:
        nxt: list[tuple[int, int]] = []
        for (x, y) in frontier:
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen:
                    continue
                if not level.in_bounds(nx, ny):
                    continue
                seen.add((nx, ny))
                nxt.append((nx, ny))
                if (nx, ny) in room_tiles and usable(nx, ny):
                    return (nx, ny)
        frontier = nxt

    for y in range(level.height):
        for x in range(level.width):
            if usable(x, y):
                return (x, y)

    raise RuntimeError(
        "safe_floor_near: no walkable, feature-free tile on level"
    )


def smallest_leaf_door(
    ground: Level, building: Building,
) -> tuple[int, int] | None:
    """Return the interior ``door_closed`` tile leading into the
    smallest BSP leaf (room) of a building's ground floor.

    Used by the shop lock pass: the backroom is the smallest leaf;
    locking the door that opens onto it adds a pick-lock / force
    beat without stranding the player from the shop counter.

    Rooms are ranked by ``len(room.floor_tiles())``. Ties break
    deterministically on ``room.rect`` (x, y, width, height).
    Door candidates among the smallest leaf's neighbours break on
    ``(x, y)``. Perimeter (entry-door) tiles are skipped so a lock
    never walls off the building entrance. Returns ``None`` when
    the ground floor has no interior door or no rooms.
    """
    if not ground.rooms:
        return None
    perim = building.shared_perimeter()
    door_candidates: list[tuple[int, int]] = []
    for y, row in enumerate(ground.tiles):
        for x, tile in enumerate(row):
            if tile.feature != "door_closed":
                continue
            if (x, y) in perim:
                continue
            door_candidates.append((x, y))
    if not door_candidates:
        return None
    smallest = min(
        ground.rooms,
        key=lambda r: (
            len(r.floor_tiles()),
            r.rect.x, r.rect.y, r.rect.width, r.rect.height,
        ),
    )
    floor_tiles = smallest.floor_tiles()
    adjacent = [
        (dx, dy) for (dx, dy) in door_candidates
        if any(
            (dx + ox, dy + oy) in floor_tiles
            for (ox, oy) in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        )
    ]
    if adjacent:
        return sorted(adjacent)[0]
    return sorted(door_candidates)[0]

"""Corridor carving for BSP dungeons."""

from __future__ import annotations

import random

from nhc.dungeon.generators._doors import _door_candidates
from nhc.dungeon.model import Level, Room, SurfaceType, Terrain, Tile


def _wall_entry(
    level: Level, room: Room, tx: int, ty: int,
) -> tuple[int, int]:
    """Find a wall tile adjacent to *room* facing (tx, ty).

    Uses _door_candidates() to get geometrically valid positions,
    then scores them by facing direction and distance to target.
    """
    cx, cy = room.rect.center
    dx, dy = tx - cx, ty - cy

    cands = _door_candidates(room)
    if not cands:
        return cx, cy

    scored: list[tuple[int, int, float]] = []
    for wx, wy, side in cands:
        wdx, wdy = wx - cx, wy - cy
        facing = wdx * dx + wdy * dy
        dist = abs(wx - tx) + abs(wy - ty)
        score = -facing * 1000 + dist
        scored.append((wx, wy, score))

    scored.sort(key=lambda c: c[2])
    return scored[0][0], scored[0][1]


def _outward(room: Room, wx: int, wy: int) -> tuple[int, int]:
    """Step one tile away from *room* starting from wall (wx, wy).

    Finds which cardinal direction leads away from the room's
    floor tiles and returns the first VOID-side position.
    Works for any room shape.
    """
    floor = room.floor_tiles()
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        if (wx + dx, wy + dy) in floor:
            # Floor is in this direction; outward is opposite
            return wx - dx, wy - dy
    # Fallback: use bounding rect logic
    r = room.rect
    if wx < r.x:
        return wx - 1, wy
    if wx >= r.x2:
        return wx + 1, wy
    if wy < r.y:
        return wx, wy - 1
    if wy >= r.y2:
        return wx, wy + 1
    return wx, wy


def _carve_line(
    level: Level, x1: int, y1: int, x2: int, y2: int,
    force: bool = False,
) -> None:
    """Carve a straight corridor line.

    Normally only replaces VOID tiles.  When *force* is True,
    also carves through WALL tiles (placing a door at each
    wall crossing) to guarantee connectivity.
    """
    def _carve_tile(cx: int, cy: int) -> None:
        if not level.in_bounds(cx, cy):
            return
        t = level.tiles[cy][cx]
        if t.terrain == Terrain.VOID:
            level.tiles[cy][cx] = Tile(
                terrain=Terrain.FLOOR, surface_type=SurfaceType.CORRIDOR,
            )
        elif force and t.terrain == Terrain.WALL:
            level.tiles[cy][cx] = Tile(
                terrain=Terrain.FLOOR, feature="door_closed",
            )

    if y1 == y2:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            _carve_tile(x, y1)
    else:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            _carve_tile(x1, y)


def _carve_corridor(
    level: Level, a: Room, b: Room, rng: random.Random,
) -> None:
    """Connect two rooms by carving through VOID only.

    1. Find wall entry on each room facing the other.
    2. Convert each wall entry to a door.
    3. Step one tile outside into VOID.
    4. Carve an L-shaped path through VOID between those points.
    """
    bx, by = b.rect.center
    ax, ay = a.rect.center

    # Wall entries
    wa_x, wa_y = _wall_entry(level, a, bx, by)
    wb_x, wb_y = _wall_entry(level, b, ax, ay)

    # Convert wall entries to doors
    # 10% secret, 5-15% locked (scales with depth), rest normal
    roll = rng.random()
    depth = getattr(level, "depth", 1)
    lock_chance = 0.05 + depth * 0.02  # 7% at depth 1, 15% at depth 5
    if roll < 0.1:
        feat = "door_secret"
    elif roll < 0.1 + lock_chance:
        feat = "door_locked"
    else:
        feat = "door_closed"

    door_feats = {
        "door_closed", "door_open", "door_secret", "door_locked",
    }
    for wx, wy in [(wa_x, wa_y), (wb_x, wb_y)]:
        t = level.tile_at(wx, wy)
        if t and t.terrain == Terrain.WALL:
            adj_feat = None
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = level.tile_at(wx + ddx, wy + ddy)
                if nb and nb.feature in door_feats:
                    adj_feat = nb.feature
                    break
            level.tiles[wy][wx] = Tile(
                terrain=Terrain.FLOOR,
                feature=adj_feat if adj_feat else feat,
            )

    sx, sy = _outward(a, wa_x, wa_y)
    ex, ey = _outward(b, wb_x, wb_y)

    # Carve L-shaped corridor through VOID only
    if rng.random() < 0.5:
        _carve_line(level, sx, sy, ex, sy)
        _carve_line(level, ex, sy, ex, ey)
    else:
        _carve_line(level, sx, sy, sx, ey)
        _carve_line(level, sx, ey, ex, ey)


def _carve_corridor_force(
    level: Level, a: Room, b: Room, rng: random.Random,
) -> None:
    """Connect two rooms, punching through walls if needed.

    Same as _carve_corridor but uses force=True on _carve_line
    to guarantee the corridor actually connects even if walls
    from other rooms are in the path.
    """
    bx, by = b.rect.center
    ax, ay = a.rect.center

    wa_x, wa_y = _wall_entry(level, a, bx, by)
    wb_x, wb_y = _wall_entry(level, b, ax, ay)

    for wx, wy in [(wa_x, wa_y), (wb_x, wb_y)]:
        t = level.tile_at(wx, wy)
        if t and t.terrain == Terrain.WALL:
            level.tiles[wy][wx] = Tile(
                terrain=Terrain.FLOOR, feature="door_closed",
            )

    sx, sy = _outward(a, wa_x, wa_y)
    ex, ey = _outward(b, wb_x, wb_y)

    if rng.random() < 0.5:
        _carve_line(level, sx, sy, ex, sy, force=True)
        _carve_line(level, ex, sy, ex, ey, force=True)
    else:
        _carve_line(level, sx, sy, sx, ey, force=True)
        _carve_line(level, sx, ey, ex, ey, force=True)

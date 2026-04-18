"""Wall building and walled-corridor cleanup for BSP dungeons."""

from __future__ import annotations

from nhc.dungeon.model import Level, Terrain, Tile


def _build_walls(level: Level) -> None:
    """Place WALL tiles around room floors only (not corridors).

    Corridors have VOID on their sides — they're narrow passages
    through darkness, not walled tunnels.  Only non-corridor
    FLOOR and WATER tiles get surrounding walls (8-neighbor).
    """
    walkable = {Terrain.FLOOR, Terrain.WATER}
    to_wall: set[tuple[int, int]] = set()

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            # Only build walls around room tiles, not corridors
            if tile.terrain not in walkable or tile.is_corridor:
                continue
            for dy in range(-1, 2):
                for dx in range(-1, 2):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if (level.in_bounds(nx, ny)
                            and level.tiles[ny][nx].terrain
                            == Terrain.VOID):
                        to_wall.add((nx, ny))

    for wx, wy in to_wall:
        level.tiles[wy][wx] = Tile(terrain=Terrain.WALL)


def _fix_walled_corridors(level: Level) -> None:
    """Remove walls causing walled-tunnel adjacency on corridors.

    For each corridor tile, if both perpendicular neighbours are
    WALL (and neither is bordering an actual room floor on its
    opposite side), demote the wall whose removal does not orphan
    a room cell.  Targeted at TempleShape clipped corners that
    place WALLs in cells the corridor would prefer to have as VOID.
    """
    def _is_room_neighbor(x: int, y: int) -> bool:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            t = level.tile_at(x + dx, y + dy)
            if (t and t.terrain in (Terrain.FLOOR, Terrain.WATER)
                    and not t.is_corridor):
                return True
        return False

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.terrain == Terrain.FLOOR
                    and tile.is_corridor):
                continue
            pairs = (
                ((x, y - 1), (x, y + 1)),  # N/S
                ((x - 1, y), (x + 1, y)),  # E/W
            )
            for (ax, ay), (bx, by) in pairs:
                a = level.tile_at(ax, ay)
                b = level.tile_at(bx, by)
                if not (a and b
                        and a.terrain == Terrain.WALL
                        and b.terrain == Terrain.WALL):
                    continue
                a_room = _is_room_neighbor(ax, ay)
                b_room = _is_room_neighbor(bx, by)
                if a_room and not b_room:
                    level.tiles[by][bx] = Tile(terrain=Terrain.VOID)
                elif b_room and not a_room:
                    level.tiles[ay][ax] = Tile(terrain=Terrain.VOID)
                elif not a_room and not b_room:
                    level.tiles[ay][ax] = Tile(terrain=Terrain.VOID)
                    level.tiles[by][bx] = Tile(terrain=Terrain.VOID)

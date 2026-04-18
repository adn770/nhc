"""Dead-end pruning, orphaned door removal, and door harmonization."""

from __future__ import annotations

import logging
import random

from nhc.dungeon.generators._corridors import _carve_corridor_force
from nhc.dungeon.model import Level, Rect, Room, Terrain, Tile

logger = logging.getLogger(__name__)

_DOOR_FEATS = {"door_closed", "door_open", "door_secret", "door_locked"}


def _adjacent_to_door(level: Level, ax: int, ay: int) -> bool:
    """True if any cardinal neighbor is a door."""
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nb = level.tile_at(ax + dx, ay + dy)
        if nb and nb.feature in _DOOR_FEATS:
            return True
    return False


def _prune_dead_ends(level: Level) -> None:
    """Iteratively remove corridor tiles with <=1 floor neighbor."""
    pruned = True
    while pruned:
        pruned = False
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (tile.terrain == Terrain.FLOOR
                        and tile.is_corridor
                        and not tile.feature):
                    continue
                if _adjacent_to_door(level, x, y):
                    continue
                floor_neighbors = 0
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if nb and nb.terrain == Terrain.FLOOR:
                        floor_neighbors += 1
                if floor_neighbors <= 1:
                    level.tiles[y][x] = Tile(terrain=Terrain.VOID)
                    pruned = True


def _handle_dead_ends(level: Level, rng: random.Random) -> None:
    """Handle remaining dead-end corridor stubs.

    For each dead end: 30% add secret door if wall adjacent,
    30% keep as atmospheric dead end, 40% prune.
    """
    changed = True
    while changed:
        changed = False
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (tile.terrain == Terrain.FLOOR
                        and tile.is_corridor
                        and not tile.feature):
                    continue
                if _adjacent_to_door(level, x, y):
                    continue
                floor_neighbors = 0
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if nb and nb.terrain == Terrain.FLOOR:
                        floor_neighbors += 1
                if floor_neighbors > 1:
                    continue
                # Dead end found
                roll = rng.random()
                if roll < 0.3:
                    # Try to place a secret door on adjacent wall
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.terrain == Terrain.WALL:
                            nb.terrain = Terrain.FLOOR
                            nb.feature = "door_secret"
                            break
                    # Keep the corridor tile
                elif roll < 0.6:
                    pass  # Keep as dead end
                else:
                    # Prune
                    level.tiles[y][x] = Tile(terrain=Terrain.VOID)
                    changed = True


def _remove_orphaned_doors(level: Level) -> None:
    """Remove doors that have no corridor on the non-room side."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in _DOOR_FEATS:
                continue
            has_room_side = False
            has_corridor_side = False
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = level.tile_at(x + dx, y + dy)
                if not nb:
                    continue
                if nb.terrain == Terrain.FLOOR and not nb.is_corridor:
                    has_room_side = True
                if nb.terrain == Terrain.FLOOR and nb.is_corridor:
                    has_corridor_side = True
            if has_room_side and not has_corridor_side:
                level.tiles[y][x] = Tile(terrain=Terrain.WALL)
                logger.debug(
                    "Removed orphaned door at (%d, %d)", x, y,
                )


def _flood_reachable(
    level: Level, sx: int, sy: int,
) -> set[tuple[int, int]]:
    """Flood-fill from (sx,sy) across FLOOR tiles."""
    visited: set[tuple[int, int]] = set()
    stack = [(sx, sy)]
    while stack:
        fx, fy = stack.pop()
        if (fx, fy) in visited:
            continue
        ft = level.tile_at(fx, fy)
        if not ft or ft.terrain != Terrain.FLOOR:
            continue
        visited.add((fx, fy))
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            stack.append((fx + dx, fy + dy))
    return visited


def _verify_connectivity(
    level: Level, rects: list[Rect], entrance: int,
    rng: random.Random,
) -> None:
    """Verify all rooms reachable via flood fill, reconnect if needed."""
    ecx, ecy = rects[entrance].center
    reconnected = 0
    for _attempt in range(len(rects)):
        reachable = _flood_reachable(level, ecx, ecy)
        found_disconnect = False
        for ri, rect in enumerate(rects):
            rcx, rcy = rect.center
            if (rcx, rcy) in reachable:
                continue
            found_disconnect = True
            best_other = None
            best_dist = 9999
            for oi, orect in enumerate(rects):
                ocx, ocy = orect.center
                if (ocx, ocy) not in reachable:
                    continue
                d = abs(rcx - ocx) + abs(rcy - ocy)
                if d < best_dist:
                    best_dist = d
                    best_other = oi
            if best_other is not None:
                _carve_corridor_force(
                    level, level.rooms[ri], level.rooms[best_other],
                    rng,
                )
                reconnected += 1
                logger.info(
                    "Reconnected room_%d to room_%d (flood-fill)",
                    ri + 1, best_other + 1,
                )
            break
        if not found_disconnect:
            break

    if reconnected:
        logger.info("Post-prune reconnection: %d corridors added",
                    reconnected)


def _harmonize_doors(level: Level) -> None:
    """Unify adjacent door types so they match."""
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in _DOOR_FEATS:
                continue
            for dx, dy in [(1, 0), (0, 1)]:
                nb = level.tile_at(x + dx, y + dy)
                if nb and nb.feature in _DOOR_FEATS:
                    if nb.feature != tile.feature:
                        nb.feature = tile.feature

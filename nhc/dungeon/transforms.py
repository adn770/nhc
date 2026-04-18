"""Post-generation transforms for structural templates.

Each transform is a pure function that modifies a Level in
place. Transforms are applied after the base generator runs
but before room types and terrain.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, Terrain


def add_cart_tracks(level: Level, rng: random.Random) -> None:
    """Mark corridor tiles as mine cart tracks.

    Walks each corridor run and marks contiguous stretches as
    tracks. Short stubs (< 3 tiles) are skipped.
    """
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if (tile.terrain == Terrain.FLOOR
                    and tile.is_corridor
                    and not tile.feature):
                tile.is_track = True


def narrow_corridors(level: Level, rng: random.Random) -> None:
    """Prune corridor tiles that have parallel neighbors.

    For crypt-style passages: where a corridor is 2+ tiles wide,
    collapse the excess back to VOID. Only removes tiles that
    don't break connectivity.
    """
    to_remove: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if not (tile.terrain == Terrain.FLOOR and tile.is_corridor):
                continue
            # Check if this tile has a corridor neighbor on both
            # perpendicular sides — sign of a wide corridor
            n = level.tile_at(x, y - 1)
            s = level.tile_at(x, y + 1)
            e = level.tile_at(x + 1, y)
            w = level.tile_at(x - 1, y)

            ns_corr = (n and n.is_corridor and n.terrain == Terrain.FLOOR
                       and s and s.is_corridor and s.terrain == Terrain.FLOOR)
            ew_corr = (e and e.is_corridor and e.terrain == Terrain.FLOOR
                       and w and w.is_corridor and w.terrain == Terrain.FLOOR)

            if ns_corr and ew_corr:
                # Junction — skip
                continue
            if not ns_corr and not ew_corr:
                # Dead end or single-width — check for wideness
                # Count corridor neighbors
                corr_neighbors = sum(
                    1 for nb in (n, s, e, w)
                    if nb and nb.is_corridor and nb.terrain == Terrain.FLOOR
                )
                if corr_neighbors >= 3 and rng.random() < 0.3:
                    to_remove.append((x, y))

    for x, y in to_remove:
        level.tiles[y][x].terrain = Terrain.VOID
        level.tiles[y][x].is_corridor = False


def add_battlements(level: Level, rng: random.Random) -> None:
    """Build a 2-tile thick outer wall ring around the level.

    Converts the outermost 2 rows/columns to WALL terrain,
    preserving any existing floor tiles (rooms/corridors that
    happen to be near the edge keep their tiles).
    """
    from nhc.dungeon.model import Tile
    for y in range(level.height):
        for x in range(level.width):
            if (x < 2 or x >= level.width - 2
                    or y < 2 or y >= level.height - 2):
                tile = level.tiles[y][x]
                if tile.terrain in (Terrain.VOID, Terrain.WALL):
                    level.tiles[y][x] = Tile(terrain=Terrain.WALL)


def add_gate(level: Level, rng: random.Random) -> None:
    """Punch gate openings through the outer battlement wall.

    Finds the midpoint of each wall side and carves a 1-tile
    wide doorway through the 2-tile thick wall. Places a
    closed door at the outer edge.
    """
    from nhc.dungeon.model import Tile
    w, h = level.width, level.height
    mid_x = w // 2
    mid_y = h // 2

    # Pick 1-2 gate positions from the 4 cardinal sides
    sides = ["south", "north", "east", "west"]
    rng.shuffle(sides)
    gate_count = rng.choice([1, 2])
    chosen = sides[:gate_count]

    for side in chosen:
        if side == "south":
            # Carve through bottom wall at mid_x
            for row in range(max(0, h - 2), h):
                level.tiles[row][mid_x] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
            level.tiles[h - 1][mid_x].feature = "door_closed"
            level.tiles[h - 1][mid_x].door_side = "south"
        elif side == "north":
            for row in range(min(2, h)):
                level.tiles[row][mid_x] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
            level.tiles[0][mid_x].feature = "door_closed"
            level.tiles[0][mid_x].door_side = "north"
        elif side == "east":
            for col in range(max(0, w - 2), w):
                level.tiles[mid_y][col] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
            level.tiles[mid_y][w - 1].feature = "door_closed"
            level.tiles[mid_y][w - 1].door_side = "east"
        elif side == "west":
            for col in range(min(2, w)):
                level.tiles[mid_y][col] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
            level.tiles[mid_y][0].feature = "door_closed"
            level.tiles[mid_y][0].door_side = "west"


def add_ore_deposits(level: Level, rng: random.Random) -> None:
    """Place ore resource markers on wall tiles near corridors.

    Scans for wall tiles adjacent to corridor floors and marks
    ~20% of them as ore deposits.
    """
    candidates: list[tuple[int, int]] = []
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.terrain != Terrain.WALL:
                continue
            # Must be adjacent to a corridor floor
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nb = level.tile_at(x + dx, y + dy)
                if (nb and nb.terrain == Terrain.FLOOR
                        and nb.is_corridor):
                    candidates.append((x, y))
                    break

    for x, y in candidates:
        if rng.random() < 0.2:
            level.tiles[y][x].feature = "ore_deposit"


TRANSFORM_REGISTRY: dict[str, callable] = {
    "add_cart_tracks": add_cart_tracks,
    "narrow_corridors": narrow_corridors,
    "add_battlements": add_battlements,
    "add_gate": add_gate,
    "add_ore_deposits": add_ore_deposits,
}

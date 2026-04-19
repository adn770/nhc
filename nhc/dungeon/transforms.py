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
    "add_ore_deposits": add_ore_deposits,
}

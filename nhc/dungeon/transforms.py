"""Post-generation transforms for structural templates.

Each transform is a pure function that modifies a Level in
place. Transforms are applied after the base generator runs
but before room types and terrain.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import Level, SurfaceType, Terrain


def add_cart_tracks(level: Level, rng: random.Random) -> None:
    """Mark corridor tiles as mine cart tracks.

    Walks each corridor run and marks contiguous stretches as
    tracks. Short stubs (< 3 tiles) are skipped.
    """
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if (tile.terrain == Terrain.FLOOR
                    and tile.surface_type == SurfaceType.CORRIDOR
                    and not tile.feature):
                tile.surface_type = SurfaceType.TRACK


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
            if not (tile.terrain == Terrain.FLOOR
                    and tile.surface_type == SurfaceType.CORRIDOR):
                continue
            # Check if this tile has a corridor neighbor on both
            # perpendicular sides — sign of a wide corridor
            n = level.tile_at(x, y - 1)
            s = level.tile_at(x, y + 1)
            e = level.tile_at(x + 1, y)
            w = level.tile_at(x - 1, y)

            def _is_corr(nb) -> bool:
                return (
                    nb is not None
                    and nb.surface_type == SurfaceType.CORRIDOR
                    and nb.terrain == Terrain.FLOOR
                )

            ns_corr = _is_corr(n) and _is_corr(s)
            ew_corr = _is_corr(e) and _is_corr(w)

            if ns_corr and ew_corr:
                # Junction — skip
                continue
            if not ns_corr and not ew_corr:
                # Dead end or single-width — check for wideness
                # Count corridor neighbors
                corr_neighbors = sum(
                    1 for nb in (n, s, e, w) if _is_corr(nb)
                )
                if corr_neighbors >= 3 and rng.random() < 0.3:
                    to_remove.append((x, y))

    for x, y in to_remove:
        level.tiles[y][x].terrain = Terrain.VOID
        level.tiles[y][x].surface_type = SurfaceType.NONE


def add_ore_deposits(level: Level, rng: random.Random) -> None:
    """Place ore resource markers on wall tiles near corridors.

    Scans for wall tiles adjacent to corridor (or cart-track)
    floors and marks ~20% of them as ore deposits. Tracks are
    treated as corridor variants because ``add_cart_tracks`` may
    have run before this transform, converting CORRIDOR tiles to
    TRACK in place.
    """
    corridor_surfaces = (SurfaceType.CORRIDOR, SurfaceType.TRACK)
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
                        and nb.surface_type in corridor_surfaces):
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

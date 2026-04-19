"""Stair placement for BSP dungeons and multi-floor Buildings."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from nhc.dungeon.generators._connectivity import _bfs_dist
from nhc.dungeon.model import Level, Rect, TempleShape, Terrain

if TYPE_CHECKING:
    from nhc.dungeon.building import Building, StairLink


def _place_stairs(
    level: Level, rects: list[Rect],
    adj: dict[int, set[int]], rng: random.Random,
) -> None:
    """Place stairs randomly with distance constraints.

    - stairs_up in a random room (entry)
    - stairs_down in a room at least half the max BFS
      distance from entry
    - ~15% chance of a second stairs_down in another
      distant room
    """
    n = len(rects)
    if n < 2:
        # Degenerate: single room gets both stairs
        cx, cy = rects[0].center
        level.tiles[cy][cx].feature = "stairs_up"
        level.rooms[0].tags.append("entry")
        level.rooms[0].tags.append("exit")
        return

    # Pick entry room randomly, but avoid TempleShape rooms so
    # the depth-2 temple sanctuary is not erased by stairs.
    non_temple = [
        i for i in range(n)
        if i >= len(level.rooms)
        or not isinstance(level.rooms[i].shape, TempleShape)
    ]
    entry_pool = non_temple if non_temple else list(range(n))
    entry = rng.choice(entry_pool)
    dists = _bfs_dist(adj, entry)
    max_dist = max(dists.values()) if dists else 1

    # Candidates for stairs_down: at least half max distance,
    # excluding TempleShape rooms.
    min_dist = max(1, max_dist // 2)
    candidates = [
        i for i, d in dists.items()
        if d >= min_dist and i != entry and i in entry_pool
    ]
    if not candidates:
        # Fallback: any non-temple room except entry, then any.
        candidates = [
            i for i in range(n)
            if i != entry and i in entry_pool
        ] or [i for i in range(n) if i != entry]

    exit_idx = rng.choice(candidates)

    # Place stairs
    sx, sy = rects[entry].center
    level.tiles[sy][sx].feature = "stairs_up"
    ex, ey = rects[exit_idx].center
    level.tiles[ey][ex].feature = "stairs_down"
    level.rooms[entry].tags.append("entry")
    level.rooms[exit_idx].tags.append("exit")

    # ~15% chance of a second stairs_down
    if rng.random() < 0.15:
        second = [
            i for i in candidates if i != exit_idx
        ]
        if second:
            idx2 = rng.choice(second)
            x2, y2 = rects[idx2].center
            level.tiles[y2][x2].feature = "stairs_down"
            level.rooms[idx2].tags.append("exit")


def _valid_stair_tiles(
    floor: Level, perimeter: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Interior floor tiles without a feature, off the shared perimeter."""
    valid: set[tuple[int, int]] = set()
    for y, row in enumerate(floor.tiles):
        for x, tile in enumerate(row):
            if tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature is not None:
                continue
            if (x, y) in perimeter:
                continue
            valid.add((x, y))
    return valid


def place_cross_floor_stairs(
    building: "Building", rng: random.Random,
) -> list["StairLink"]:
    """Place stairs between adjacent floors of ``building``.

    For each adjacent (i, i+1) pair, picks a tile valid on both
    floors (FLOOR terrain, no pre-existing feature, not on the
    shared perimeter), marks lower's feature as ``stairs_up`` and
    upper's as ``stairs_down``, and records a
    :class:`StairLink`.

    If ``building.descent`` is set, also places a ``stairs_down``
    on the ground floor and appends a descent ``StairLink`` whose
    ``to_floor`` is the ``DungeonRef``.

    Raises ``ValueError`` if no shared valid tile exists for some
    adjacent pair or if the descent cannot be placed.
    """
    # Deferred import to break the circular building <-> _stairs link.
    from nhc.dungeon.building import StairLink

    perimeter = building.shared_perimeter()
    used: dict[int, set[tuple[int, int]]] = {}
    links: list[StairLink] = []

    def _pick(floor_idx: int) -> tuple[int, int]:
        floor = building.floors[floor_idx]
        pool = _valid_stair_tiles(floor, perimeter) - used.get(
            floor_idx, set(),
        )
        if not pool:
            raise ValueError(
                f"no valid stair tile on floor {floor_idx}"
            )
        return rng.choice(sorted(pool))

    def _shared_pick(lo: int, hi: int) -> tuple[int, int]:
        lower = _valid_stair_tiles(
            building.floors[lo], perimeter,
        ) - used.get(lo, set())
        upper = _valid_stair_tiles(
            building.floors[hi], perimeter,
        ) - used.get(hi, set())
        shared = lower & upper
        if not shared:
            raise ValueError(
                f"no valid stair tile shared between floors "
                f"{lo} and {hi}"
            )
        return rng.choice(sorted(shared))

    for i in range(len(building.floors) - 1):
        tile = _shared_pick(i, i + 1)
        x, y = tile
        building.floors[i].tiles[y][x].feature = "stairs_up"
        building.floors[i + 1].tiles[y][x].feature = "stairs_down"
        used.setdefault(i, set()).add(tile)
        used.setdefault(i + 1, set()).add(tile)
        links.append(StairLink(
            from_floor=i, to_floor=i + 1,
            from_tile=tile, to_tile=tile,
        ))

    if building.descent is not None:
        tile = _pick(0)
        x, y = tile
        building.floors[0].tiles[y][x].feature = "stairs_down"
        used.setdefault(0, set()).add(tile)
        links.append(StairLink(
            from_floor=0, to_floor=building.descent,
            from_tile=tile, to_tile=(0, 0),
        ))

    return links


def flip_building_stair_semantics(building: "Building") -> None:
    """Flip cross-floor stair features on every floor of a building.

    :func:`place_cross_floor_stairs` uses dungeon conventions: the
    lower-index floor's stair feature is ``stairs_up`` because
    climbing reaches a lower ``depth``. In a multi-floor building
    the physical direction is inverted: ``floor_index + 1`` is the
    floor *above*, and the engine treats that as a ``depth``
    increase reached by the ``descend`` action. Flipping the
    feature names on both sides of each cross-floor stair link
    keeps the engine's floor-transition logic correct.

    The descent stair (when ``building.descent is not None``) is
    excluded from the flip: it leads physically downward to the
    cellar, so it must stay as ``stairs_down`` on the ground
    floor regardless of the cross-floor inversion.
    """
    from nhc.hexcrawl.model import DungeonRef

    cross_tiles: set[tuple[int, int, int]] = set()
    for link in building.stair_links:
        if isinstance(link.to_floor, DungeonRef):
            continue
        cross_tiles.add((link.from_floor, *link.from_tile))
        cross_tiles.add((link.to_floor, *link.to_tile))
    swap = {"stairs_up": "stairs_down", "stairs_down": "stairs_up"}
    for idx, floor in enumerate(building.floors):
        for y, row in enumerate(floor.tiles):
            for x, tile in enumerate(row):
                if (idx, x, y) not in cross_tiles:
                    continue
                if tile.feature in swap:
                    tile.feature = swap[tile.feature]

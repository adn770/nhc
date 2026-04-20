"""Stair placement for BSP dungeons and multi-floor Buildings."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING, Callable

from nhc.dungeon.generators._connectivity import _bfs_dist
from nhc.dungeon.model import Level, Rect, RoomShape, TempleShape, Terrain

if TYPE_CHECKING:
    from nhc.dungeon.building import Building, StairLink
    from nhc.hexcrawl.model import DungeonRef


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


def _pick_stair_tile(
    floor: Level, perimeter: set[tuple[int, int]],
    exclude: set[tuple[int, int]], rng: random.Random,
    *,
    avoid_tile: tuple[int, int] | None = None,
) -> tuple[int, int]:
    """Pick one walkable, featureless, non-perimeter tile on
    ``floor``.

    When ``avoid_tile`` is given and the floor has ≥ 2 rooms, the
    picker prefers a tile in the room whose centroid is furthest
    from the room containing ``avoid_tile`` — the "diagonally
    opposite leaf" heuristic from M10. Falls back to a uniform
    pick when the floor has one room or no tile is available in
    the preferred room.
    """
    pool = _valid_stair_tiles(floor, perimeter) - exclude
    if not pool:
        raise ValueError("no valid stair tile on floor")
    if avoid_tile is not None and len(floor.rooms) >= 2:
        preferred = _opposite_leaf_tiles(
            floor, avoid_tile, pool,
        )
        if preferred:
            return rng.choice(sorted(preferred))
    return rng.choice(sorted(pool))


def _opposite_leaf_tiles(
    floor: Level, avoid_tile: tuple[int, int],
    pool: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Return the subset of ``pool`` that lies in the room whose
    centroid is furthest from the room containing ``avoid_tile``.

    Returns an empty set when the source room can't be identified
    or the opposite room has no tiles in ``pool``.
    """
    source = _room_containing(floor, avoid_tile)
    if source is None:
        return set()
    sx, sy = source.rect.center
    others = [r for r in floor.rooms if r is not source]
    if not others:
        return set()
    others.sort(
        key=lambda r: (
            (r.rect.center[0] - sx) ** 2
            + (r.rect.center[1] - sy) ** 2
        ),
        reverse=True,
    )
    target = others[0]
    target_tiles = {
        (x, y)
        for y in range(target.rect.y, target.rect.y2)
        for x in range(target.rect.x, target.rect.x2)
    }
    return pool & target_tiles


def _room_containing(floor: Level, xy: tuple[int, int]):
    x, y = xy
    for room in floor.rooms:
        r = room.rect
        if r.x <= x < r.x2 and r.y <= y < r.y2:
            return room
    return None


def build_floors_with_stairs(
    *,
    building_id: str,
    base_shape: RoomShape,
    base_rect: Rect,
    n_floors: int,
    descent: "DungeonRef | None",
    rng: random.Random,
    build_floor_fn: Callable[
        [int, int, frozenset[tuple[int, int]]], Level,
    ],
) -> tuple[list[Level], list["StairLink"]]:
    """Interleaved floor-build + per-link stair placement.

    For each adjacent pair ``(i, i+1)``, pick a walkable tile on
    floor ``i`` (which has just been partitioned) and thread it
    into floor ``i+1``'s partitioner call via
    ``required_walkable``. See
    ``design/building_interiors.md`` — the stair-alignment
    invariant is per-link, not per-building.

    ``build_floor_fn(floor_idx, n_floors, required_walkable)``
    builds and returns a :class:`Level`.
    """
    from nhc.dungeon.building import StairLink

    perimeter = base_shape.perimeter_tiles(base_rect)
    floors: list[Level] = []
    links: list[StairLink] = []
    used: dict[int, set[tuple[int, int]]] = {}
    required: frozenset[tuple[int, int]] = frozenset()
    pending_upper: tuple[int, tuple[int, int]] | None = None

    for idx in range(n_floors):
        level = build_floor_fn(idx, n_floors, required)
        floors.append(level)

        # Stamp stairs_down landing from the prior link.
        if pending_upper is not None:
            prev_idx, prev_tile = pending_upper
            assert prev_idx == idx - 1, (
                "pending stair landing came from a non-adjacent floor"
            )
            px, py = prev_tile
            assert level.tiles[py][px].terrain is Terrain.FLOOR, (
                f"required_walkable tile {prev_tile} lost its FLOOR "
                f"on floor {idx}"
            )
            level.tiles[py][px].feature = "stairs_down"
            used.setdefault(idx, set()).add(prev_tile)
            pending_upper = None

        # Pick the stair for the link to the next floor, if any.
        if idx + 1 < n_floors:
            # If a stairs_down landed on this floor from the
            # previous link, place the next stairs_up in a room
            # diagonally opposite so the traversal spirals.
            landing = None
            for prev_tile in used.get(idx, set()):
                if level.tiles[prev_tile[1]][prev_tile[0]].feature == (
                    "stairs_down"
                ):
                    landing = prev_tile
                    break
            tile = _pick_stair_tile(
                level, perimeter, used.get(idx, set()), rng,
                avoid_tile=landing,
            )
            fx, fy = tile
            level.tiles[fy][fx].feature = "stairs_up"
            used.setdefault(idx, set()).add(tile)
            links.append(StairLink(
                from_floor=idx, to_floor=idx + 1,
                from_tile=tile, to_tile=tile,
            ))
            required = frozenset({tile})
            pending_upper = (idx, tile)
        else:
            required = frozenset()

    if descent is not None:
        tile = _pick_stair_tile(
            floors[0], perimeter, used.get(0, set()), rng,
        )
        fx, fy = tile
        floors[0].tiles[fy][fx].feature = "stairs_down"
        used.setdefault(0, set()).add(tile)
        links.append(StairLink(
            from_floor=0, to_floor=descent,
            from_tile=tile, to_tile=(0, 0),
        ))

    return floors, links



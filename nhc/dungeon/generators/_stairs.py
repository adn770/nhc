"""Stair placement for BSP dungeons."""

from __future__ import annotations

import random

from nhc.dungeon.generators._connectivity import _bfs_dist
from nhc.dungeon.model import Level, Rect, TempleShape


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

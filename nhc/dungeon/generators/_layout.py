"""Layout strategies for BSP dungeons.

Each strategy takes the list of room rects and an RNG, and returns
a connectivity plan: a list of (room_index, room_index) pairs that
should be connected by corridors, plus the entrance and exit indices.
"""

from __future__ import annotations

import random

from nhc.dungeon.generators._connectivity import (
    _bfs,
    _bfs_dist,
    _center_dist,
    _find_neighbors,
)
from nhc.dungeon.model import Rect


def plan_default(
    rects: list[Rect], connectivity: float, rng: random.Random,
) -> tuple[list[tuple[int, int]], int, int]:
    """Default BSP layout: main path + extra loops.

    Returns (pairs_to_connect, entrance_idx, exit_idx).
    """
    neighbors = _find_neighbors(rects)
    adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
    for i, j in neighbors:
        adj[i].add(j)
        adj[j].add(i)

    entrance = 0
    dists = _bfs_dist(adj, entrance)
    exit_idx = max(dists, key=dists.get) if dists else len(rects) - 1

    pairs: list[tuple[int, int]] = []
    connected: set[tuple[int, int]] = set()

    # Main path
    main_path = _bfs(adj, entrance, exit_idx)
    if main_path:
        for k in range(len(main_path) - 1):
            a, b = main_path[k], main_path[k + 1]
            pair = (min(a, b), max(a, b))
            if pair not in connected:
                connected.add(pair)
                pairs.append(pair)

    # Extra loops
    for i, j in neighbors:
        pair = (min(i, j), max(i, j))
        if pair not in connected and rng.random() < connectivity * 0.5:
            connected.add(pair)
            pairs.append(pair)

    # Ensure full reachability
    changed = True
    while changed:
        changed = False
        reachable = _bfs_dist(adj, entrance)
        for idx in range(len(rects)):
            if idx in reachable:
                continue
            best_other = None
            best_dist = 9999
            for other in reachable:
                d = _center_dist(rects[idx], rects[other])
                if d < best_dist:
                    best_dist = d
                    best_other = other
            if best_other is not None:
                pair = (min(idx, best_other), max(idx, best_other))
                connected.add(pair)
                adj[idx].add(best_other)
                adj[best_other].add(idx)
                pairs.append(pair)
                changed = True
                break

    return pairs, entrance, exit_idx


def plan_radial(
    rects: list[Rect], connectivity: float, rng: random.Random,
) -> tuple[list[tuple[int, int]], int, int]:
    """Radial layout: central hub connected to all other rooms.

    Picks the room closest to the map center as the hub.
    All other rooms connect directly to the hub (star topology).
    A few extra spoke-to-spoke links add loops.
    """
    if len(rects) < 2:
        return [], 0, 0

    # Find the map's geometric center
    all_cx = sum(r.center[0] for r in rects) / len(rects)
    all_cy = sum(r.center[1] for r in rects) / len(rects)

    # Hub = room closest to center
    hub = min(
        range(len(rects)),
        key=lambda i: abs(rects[i].center[0] - all_cx)
        + abs(rects[i].center[1] - all_cy),
    )

    pairs: list[tuple[int, int]] = []
    connected: set[tuple[int, int]] = set()

    # Connect every room to the hub
    spokes = [i for i in range(len(rects)) if i != hub]
    for s in spokes:
        pair = (min(hub, s), max(hub, s))
        if pair not in connected:
            connected.add(pair)
            pairs.append(pair)

    # Sort spokes by angle from hub for ring connections
    hcx, hcy = rects[hub].center
    import math
    spokes_by_angle = sorted(
        spokes,
        key=lambda i: math.atan2(
            rects[i].center[1] - hcy,
            rects[i].center[0] - hcx,
        ),
    )

    # Add some ring links between adjacent spokes
    for k in range(len(spokes_by_angle)):
        if rng.random() < connectivity * 0.4:
            a = spokes_by_angle[k]
            b = spokes_by_angle[(k + 1) % len(spokes_by_angle)]
            pair = (min(a, b), max(a, b))
            if pair not in connected:
                connected.add(pair)
                pairs.append(pair)

    # Entrance = hub, exit = farthest spoke
    exit_idx = max(
        spokes,
        key=lambda i: _center_dist(rects[hub], rects[i]),
    )

    return pairs, hub, exit_idx


def plan_linear(
    rects: list[Rect], connectivity: float, rng: random.Random,
) -> tuple[list[tuple[int, int]], int, int]:
    """Linear layout: long trunk with short side branches.

    Sorts rooms along the longest axis and chains them.
    A few side branches connect to the trunk for variety.
    """
    if len(rects) < 2:
        return [], 0, 0

    # Determine dominant axis from map extents
    xs = [r.center[0] for r in rects]
    ys = [r.center[1] for r in rects]
    x_span = max(xs) - min(xs)
    y_span = max(ys) - min(ys)

    # Sort rooms along the dominant axis
    if x_span >= y_span:
        order = sorted(range(len(rects)), key=lambda i: rects[i].center[0])
    else:
        order = sorted(range(len(rects)), key=lambda i: rects[i].center[1])

    pairs: list[tuple[int, int]] = []
    connected: set[tuple[int, int]] = set()

    # Main trunk: chain rooms in order
    for k in range(len(order) - 1):
        a, b = order[k], order[k + 1]
        pair = (min(a, b), max(a, b))
        if pair not in connected:
            connected.add(pair)
            pairs.append(pair)

    # Side branches: occasionally skip-connect for variety
    for k in range(len(order) - 2):
        if rng.random() < connectivity * 0.3:
            a, b = order[k], order[k + 2]
            pair = (min(a, b), max(a, b))
            if pair not in connected:
                connected.add(pair)
                pairs.append(pair)

    entrance = order[0]
    exit_idx = order[-1]
    return pairs, entrance, exit_idx


LAYOUT_STRATEGIES: dict[str, callable] = {
    "default": plan_default,
    "radial": plan_radial,
    "linear": plan_linear,
}

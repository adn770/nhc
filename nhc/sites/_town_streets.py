"""Street network for town surfaces (Phase 2).

Replaces the legacy "every walkable tile is STREET" surface fill
with a tagged graph: routed STREET paths thread between cluster
bboxes, GARDEN tiles fill cluster-internal walkable patches (e.g.
courtyard interiors), and FIELD tiles cover the palisade
periphery between the outermost clusters and the wall.

Routing uses Manhattan A* with a wobble penalty (Q9): straight
runs longer than 4 tiles pay a small extra cost so the resulting
streets bend slightly off optimal, reading hand-drawn rather than
ruler-straight. Town and city sites carry a 2-tile-wide main
spine connecting the gates and the cluster ring; hamlet and
village sites use uniform 1-tile branches direct to each cluster
(Q2). Branches off the spine connect every cluster centroid to
the nearest spine tile (or gate, for hamlet / village).

See ``town_redesign_plan.md`` Phase 2 for the full design.
"""

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING

from nhc.dungeon.model import Rect, SurfaceType, Terrain, Tile

if TYPE_CHECKING:
    from nhc.dungeon.building import Building
    from nhc.dungeon.model import Level
    from nhc.sites._site import Enclosure
    from nhc.sites._town_layout import _ClusterPlan


SPINE_WIDTH_LARGE = 2
"""2-tile-wide main spine for town / city (Q2)."""

BRANCH_WIDTH = 1
"""1-tile-wide branches connecting clusters to the spine /
 gates (Q2)."""

WOBBLE_PENALTY = 0.5
WOBBLE_RUN_THRESHOLD = 4

DEAD_END_PRUNE_LENGTH = 2
"""Trim trailing branches shorter than this number of tiles
 unless they terminate at a cluster door candidate or a gate."""


# ── A* router ────────────────────────────────────────────────


def _neighbours_4(x: int, y: int) -> list[tuple[int, int]]:
    return [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]


def _route_path(
    start: tuple[int, int],
    goal: tuple[int, int],
    walkable: set[tuple[int, int]],
    extra_cost: dict[tuple[int, int], float] | None = None,
    max_steps: int = 20000,
) -> list[tuple[int, int]]:
    """Manhattan A* on ``walkable`` with a wobble penalty.

    Returns the tile path from ``start`` to ``goal`` inclusive.
    Returns ``[]`` when no path exists. The wobble penalty adds
    ``WOBBLE_PENALTY`` per tile of consecutive straight movement
    past ``WOBBLE_RUN_THRESHOLD``, encouraging the router to bend
    so streets read hand-drawn instead of ruler-straight (Q9).

    State carries the running straight-step count + last-direction
    so the wobble cost depends on movement history, not just the
    tile.
    """
    if start == goal:
        return [start]
    if start not in walkable or goal not in walkable:
        return []
    extra_cost = extra_cost or {}

    # Open list entries: (f, g, tile, last_dir, run_len)
    open_set: list = []
    heapq.heappush(
        open_set, (0.0, 0.0, start, (0, 0), 0),
    )
    came_from: dict[
        tuple[tuple[int, int], tuple[int, int]],
        tuple[tuple[int, int], tuple[int, int]],
    ] = {}
    best_g: dict[tuple[tuple[int, int], tuple[int, int]], float] = {
        (start, (0, 0)): 0.0,
    }
    steps = 0

    while open_set and steps < max_steps:
        steps += 1
        f, g, current, last_dir, run_len = heapq.heappop(open_set)
        if current == goal:
            return _reconstruct_path(
                came_from, current, last_dir,
            )
        for nx, ny in _neighbours_4(*current):
            nb = (nx, ny)
            if nb not in walkable:
                continue
            dx = nx - current[0]
            dy = ny - current[1]
            move_dir = (dx, dy)
            step_cost = 1.0 + extra_cost.get(nb, 0.0)
            new_run = run_len + 1 if move_dir == last_dir else 1
            if new_run > WOBBLE_RUN_THRESHOLD:
                step_cost += WOBBLE_PENALTY
            tentative = g + step_cost
            key = (nb, move_dir)
            if tentative < best_g.get(key, float("inf")):
                best_g[key] = tentative
                came_from[key] = (current, last_dir)
                h = abs(nx - goal[0]) + abs(ny - goal[1])
                heapq.heappush(
                    open_set,
                    (tentative + h, tentative, nb, move_dir, new_run),
                )
    return []


def _reconstruct_path(
    came_from: dict, current: tuple[int, int],
    last_dir: tuple[int, int],
) -> list[tuple[int, int]]:
    path = [current]
    key = (current, last_dir)
    while key in came_from:
        prev, prev_dir = came_from[key]
        path.append(prev)
        key = (prev, prev_dir)
    path.reverse()
    return path


# ── Walkable / cluster helpers ───────────────────────────────


def _cluster_centroid(
    plan: "_ClusterPlan",
) -> tuple[int, int]:
    """Geometric centre of the cluster's member rects. Lies
    inside a building footprint; use :func:`_cluster_route_anchor`
    when a walkable target is required."""
    xs: list[int] = []
    ys: list[int] = []
    for m in plan.members:
        cx = m.rect.x + m.rect.width // 2
        cy = m.rect.y + m.rect.height // 2
        xs.append(cx)
        ys.append(cy)
    return (sum(xs) // len(xs), sum(ys) // len(ys))


def _cluster_route_anchor(
    plan: "_ClusterPlan",
    walkable: set[tuple[int, int]],
) -> tuple[int, int] | None:
    """Pick a walkable tile near the cluster's geometric centroid
    that streets can terminate on. Searches the bbox border first
    (the 1-tile buffer ring is always walkable for clusters that
    fit inside the palisade) and falls back to the wider bbox
    interior for hollow clusters (courtyard, L-block notch)."""
    centroid = _cluster_centroid(plan)
    bbox = plan.bbox
    border: list[tuple[int, int]] = []
    for x in range(bbox.x, bbox.x2):
        border.append((x, bbox.y))
        border.append((x, bbox.y2 - 1))
    for y in range(bbox.y + 1, bbox.y2 - 1):
        border.append((bbox.x, y))
        border.append((bbox.x2 - 1, y))
    border_walkable = [t for t in border if t in walkable]
    if border_walkable:
        return min(
            border_walkable,
            key=lambda t: abs(t[0] - centroid[0])
            + abs(t[1] - centroid[1]),
        )
    # Fall back: scan the full bbox interior.
    interior: list[tuple[int, int]] = []
    for y in range(bbox.y, bbox.y2):
        for x in range(bbox.x, bbox.x2):
            if (x, y) in walkable:
                interior.append((x, y))
    if not interior:
        return None
    return min(
        interior,
        key=lambda t: abs(t[0] - centroid[0])
        + abs(t[1] - centroid[1]),
    )


def _cluster_bbox_envelope(
    plans: list["_ClusterPlan"],
) -> Rect:
    xs_lo = min(p.bbox.x for p in plans)
    ys_lo = min(p.bbox.y for p in plans)
    xs_hi = max(p.bbox.x2 for p in plans)
    ys_hi = max(p.bbox.y2 for p in plans)
    return Rect(xs_lo, ys_lo, xs_hi - xs_lo, ys_hi - ys_lo)


def gates_y_for_cluster_set(
    plans: list["_ClusterPlan"], gate_count: int,
) -> list[int]:
    """Q14: distribute ``gate_count`` y-coordinates across the
    cluster-bbox-set y-extent so the gates align with the
    inhabited part of the surface, not the empty headers."""
    if not plans:
        return [0] * gate_count
    envelope = _cluster_bbox_envelope(plans)
    if gate_count <= 1:
        return [envelope.y + envelope.height // 2]
    step = envelope.height // (gate_count + 1)
    return [
        envelope.y + step * (i + 1) for i in range(gate_count)
    ]


def _palisade_interior_walkable(
    enclosure: "Enclosure",
    surface_w: int, surface_h: int,
    blocked: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    xs = [p[0] for p in enclosure.polygon]
    ys = [p[1] for p in enclosure.polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    walkable: set[tuple[int, int]] = set()
    for y in range(max(0, min_y), min(surface_h, max_y)):
        for x in range(max(0, min_x), min(surface_w, max_x)):
            if (x, y) in blocked:
                continue
            walkable.add((x, y))
    return walkable


def _open_surface_walkable(
    surface_w: int, surface_h: int,
    blocked: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    walkable: set[tuple[int, int]] = set()
    for y in range(surface_h):
        for x in range(surface_w):
            if (x, y) in blocked:
                continue
            walkable.add((x, y))
    return walkable


# ── Spine / branch routing ───────────────────────────────────


def _gate_anchor(
    gate: tuple[int, int, int],
    walkable: set[tuple[int, int]],
    enclosure_bbox: tuple[int, int, int, int],
) -> tuple[int, int] | None:
    """Pick the walkable tile one step inside the palisade from a
    gate origin. Gates lie on the wall x; the anchor is the
    first walkable tile along the wall normal."""
    gx, gy, _ = gate
    min_x, _, max_x, _ = enclosure_bbox
    if gx == min_x:
        candidate = (gx, gy)
    elif gx == max_x:
        candidate = (gx - 1, gy)
    else:
        candidate = (gx, gy)
    if candidate in walkable:
        return candidate
    # Search nearby for a walkable tile (gate may be off-grid by
    # one tile due to palisade vertex semantics).
    for dx in (-1, 1, -2, 2):
        for dy in (0, -1, 1, -2, 2):
            spot = (candidate[0] + dx, candidate[1] + dy)
            if spot in walkable:
                return spot
    return None


def _nearest_in(
    target: tuple[int, int], pool: set[tuple[int, int]],
) -> tuple[int, int] | None:
    best, best_d = None, 1 << 30
    for tx, ty in pool:
        d = abs(tx - target[0]) + abs(ty - target[1])
        if d < best_d:
            best, best_d = (tx, ty), d
    return best


def _widen_path(
    path: list[tuple[int, int]],
    walkable: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Thicken a path to 2-tile width along the perpendicular
    axis, where the surrounding tile is walkable."""
    widened: set[tuple[int, int]] = set(path)
    for i, (x, y) in enumerate(path):
        if i + 1 < len(path):
            nx, ny = path[i + 1]
            dx, dy = nx - x, ny - y
        elif i > 0:
            px, py = path[i - 1]
            dx, dy = x - px, y - py
        else:
            dx, dy = 0, 0
        # Pick the perpendicular direction.
        if dx != 0:
            extras = [(x, y + 1)]
        elif dy != 0:
            extras = [(x + 1, y)]
        else:
            extras = []
        for ex, ey in extras:
            if (ex, ey) in walkable:
                widened.add((ex, ey))
    return widened


def _route_spine_paths(
    plans: list["_ClusterPlan"],
    gate_anchors: list[tuple[int, int]],
    walkable: set[tuple[int, int]],
) -> list[list[tuple[int, int]]]:
    """Route the spine as a list of waypoint-to-waypoint paths.

    Each path is an ordered tile list (4-connected); callers can
    widen each path with :func:`_widen_path` while still
    maintaining direction. With two gates the spine connects
    ``gate0 -> ... -> gate1`` visiting every cluster anchor in
    nearest-neighbour order; with one gate it routes
    ``gate -> cluster anchors`` and stops, since closing the loop
    back to a single gate would double the spine.
    """
    if not gate_anchors:
        return []
    cluster_anchors = [
        _cluster_route_anchor(p, walkable) for p in plans
    ]
    cluster_anchors = [a for a in cluster_anchors if a is not None]
    if len(gate_anchors) >= 2:
        order = _nearest_neighbour_order(
            gate_anchors[0], cluster_anchors, gate_anchors[-1],
        )
        waypoints = [gate_anchors[0]] + order + [gate_anchors[-1]]
    elif cluster_anchors:
        order = _nearest_neighbour_order(
            gate_anchors[0], cluster_anchors, None,
        )
        waypoints = [gate_anchors[0]] + order
    else:
        return []
    paths: list[list[tuple[int, int]]] = []
    for i in range(len(waypoints) - 1):
        path = _route_path(
            waypoints[i], waypoints[i + 1], walkable,
        )
        if path:
            paths.append(path)
    return paths


def _nearest_neighbour_order(
    start: tuple[int, int],
    centroids: list[tuple[int, int]],
    end: tuple[int, int] | None,
) -> list[tuple[int, int]]:
    """Order centroids greedily nearest-first from ``start``.

    The optional ``end`` parameter biases the *last* hop toward
    proximity to the end gate (so the chain naturally finishes
    near the second gate)."""
    remaining = list(centroids)
    ordered: list[tuple[int, int]] = []
    cursor = start
    while remaining:
        if end is not None and len(remaining) == 1:
            ordered.append(remaining.pop())
            break
        nearest = min(
            remaining,
            key=lambda c: abs(c[0] - cursor[0]) + abs(c[1] - cursor[1]),
        )
        ordered.append(nearest)
        remaining.remove(nearest)
        cursor = nearest
    return ordered


def _route_branches(
    plans: list["_ClusterPlan"],
    spine: set[tuple[int, int]],
    gate_anchors: list[tuple[int, int]],
    walkable: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Connect every cluster's route anchor to the nearest spine
    tile or gate anchor.

    For sites without gates (hamlet), the first cluster's anchor
    seeds the connected network and subsequent clusters chain to
    the growing pool, so all clusters end up reachable from each
    other via STREET tiles.
    """
    branches: set[tuple[int, int]] = set()
    target_pool: set[tuple[int, int]] = set(spine)
    target_pool.update(gate_anchors)
    if not target_pool and plans:
        seed_anchor = _cluster_route_anchor(plans[0], walkable)
        if seed_anchor is not None:
            target_pool.add(seed_anchor)
    for plan in plans:
        anchor = _cluster_route_anchor(plan, walkable)
        if anchor is None:
            continue
        if anchor in target_pool:
            continue
        target = _nearest_in(anchor, target_pool)
        if target is None:
            continue
        path = _route_path(anchor, target, walkable)
        if not path:
            continue
        branches.update(path)
        target_pool.update(path)
    return branches


def _prune_dead_ends(
    streets: set[tuple[int, int]],
    anchors: set[tuple[int, int]],
) -> set[tuple[int, int]]:
    """Trim branches shorter than DEAD_END_PRUNE_LENGTH that don't
    end at an anchor (gate or cluster door candidate)."""
    pruned = set(streets)
    changed = True
    while changed:
        changed = False
        # A tile is a dead-end if it has only one STREET neighbour
        # and is not in anchors.
        for tile in list(pruned):
            if tile in anchors:
                continue
            nbs = [
                (tile[0] + dx, tile[1] + dy)
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            ]
            count = sum(1 for nb in nbs if nb in pruned)
            if count <= 1:
                pruned.discard(tile)
                changed = True
    return pruned


# ── Walkable classification ──────────────────────────────────


def _classify_walkable_tiles(
    walkable: set[tuple[int, int]],
    streets: set[tuple[int, int]],
    cluster_bboxes: list[Rect],
) -> dict[tuple[int, int], SurfaceType]:
    """Tag each walkable tile as STREET / GARDEN / FIELD.

    GARDEN: walkable tile inside any cluster bbox (cluster-internal
    open patch — courtyard interior, L-block notch, internal
    buffer).
    FIELD: walkable tile outside every cluster bbox (palisade /
    surface periphery — where vegetation lands in Phase 4a).
    STREET overrides both classifications when the tile is on a
    routed path.
    """
    out: dict[tuple[int, int], SurfaceType] = {}
    for tile in walkable:
        if tile in streets:
            out[tile] = SurfaceType.STREET
            continue
        in_cluster = False
        for bbox in cluster_bboxes:
            if (bbox.x <= tile[0] < bbox.x2
                    and bbox.y <= tile[1] < bbox.y2):
                in_cluster = True
                break
        out[tile] = SurfaceType.GARDEN if in_cluster else SurfaceType.FIELD
    return out


# ── Top-level orchestration ──────────────────────────────────


def compute_town_street_network(
    cluster_plans: list["_ClusterPlan"],
    enclosure: "Enclosure | None",
    surface_w: int, surface_h: int,
    blocked: set[tuple[int, int]],
    size_class: str,
) -> tuple[set[tuple[int, int]], dict[tuple[int, int], SurfaceType]]:
    """Compute STREET tiles + per-tile surface classification for
    a town surface.

    Returns ``(street_tiles, classification)`` where
    ``classification`` covers every walkable tile. STREET tiles
    are routed via A*; the remainder are GARDEN (inside a cluster
    bbox) or FIELD (palisade periphery / open surface).
    """
    if enclosure is not None:
        walkable = _palisade_interior_walkable(
            enclosure, surface_w, surface_h, blocked,
        )
        xs = [p[0] for p in enclosure.polygon]
        ys = [p[1] for p in enclosure.polygon]
        env_bbox = (min(xs), min(ys), max(xs), max(ys))
        gate_anchors: list[tuple[int, int]] = []
        for gate in enclosure.gates:
            anchor = _gate_anchor(gate, walkable, env_bbox)
            if anchor is not None:
                gate_anchors.append(anchor)
    else:
        walkable = _open_surface_walkable(
            surface_w, surface_h, blocked,
        )
        gate_anchors = []

    # Spine pass: route through every cluster anchor connecting
    # the gates. Always runs when gates exist so villages stay
    # gate-to-gate connected; only town / city widen the spine to
    # 2 tiles (Q2).
    streets: set[tuple[int, int]] = set()
    if gate_anchors:
        spine_paths = _route_spine_paths(
            cluster_plans, gate_anchors, walkable,
        )
        for path in spine_paths:
            streets.update(path)
            if size_class in ("town", "city"):
                streets |= _widen_path(path, walkable)

    branches = _route_branches(
        cluster_plans, streets, gate_anchors, walkable,
    )
    streets |= branches

    cluster_anchors_set: set[tuple[int, int]] = set()
    for p in cluster_plans:
        a = _cluster_route_anchor(p, walkable)
        if a is not None:
            cluster_anchors_set.add(a)
    anchors = set(gate_anchors) | cluster_anchors_set
    streets = _prune_dead_ends(streets, anchors)

    classification = _classify_walkable_tiles(
        walkable, streets, [p.bbox for p in cluster_plans],
    )
    return streets, classification


def paint_surface(
    surface: "Level",
    classification: dict[tuple[int, int], SurfaceType],
) -> None:
    """Stamp each classified tile onto ``surface``.

    GARDEN tiles render as ``Terrain.GRASS`` so the theme grass
    tint + blade strokes appear; the GARDEN surface_type layers
    a hoe-row overlay on top via the unified rendering pipeline.
    """
    for (x, y), kind in classification.items():
        if not surface.in_bounds(x, y):
            continue
        terrain = (
            Terrain.GRASS
            if kind is SurfaceType.GARDEN
            else Terrain.FLOOR
        )
        surface.tiles[y][x] = Tile(
            terrain=terrain, surface_type=kind,
        )

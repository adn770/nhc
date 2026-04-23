"""Edge-wall engine helpers.

See ``design/building_interiors.md`` — interior partitioning
walls are canonical ``(x, y, side)`` entries in
:attr:`Level.interior_edges`. Sight and movement consult that
set via :func:`edge_blocks_sight` and :func:`edge_blocks_movement`.
Doors suppress the edge beneath them when open, via the tile's
``door_side`` metadata; closed doors keep blocking through the
existing tile-feature path.

A BFS-based shadow helper (:func:`edge_shadow_tiles`) lets callers
(notably the FOV pre-pass) skip tiles that can't be reached from
an origin without crossing a walled or closed-door edge. The FOV
raycast uses this shadow set as an additional blocker layer so
the existing tile-based shadowcast can stay unchanged.
"""

from __future__ import annotations

from collections import deque

from nhc.dungeon.model import Level, canonicalize, edge_between


_OPEN_DOOR_FEATURES = frozenset({"door_open"})


def _door_side_suppresses_edge(
    tile_x: int, tile_y: int, door_side: str,
    edge_x: int, edge_y: int, edge_side: str,
) -> bool:
    """Return True if the door on ``(tile_x, tile_y)`` with the
    given ``door_side`` targets the canonical edge
    ``(edge_x, edge_y, edge_side)``."""
    if not door_side:
        return False
    # Door's target edge in canonical form.
    target = canonicalize(tile_x, tile_y, door_side)
    return target == (edge_x, edge_y, edge_side)


def edge_has_open_door(
    level: Level, edge_x: int, edge_y: int, edge_side: str,
) -> bool:
    """Return True if an open door on either adjacent tile targets
    the given canonical edge."""
    # Canonical form stores only north / west. The two adjacent
    # tiles for "north" are (x, y-1) and (x, y); for "west" they
    # are (x-1, y) and (x, y).
    if edge_side == "north":
        candidates = [
            (edge_x, edge_y - 1),  # tile above the edge
            (edge_x, edge_y),      # tile below the edge
        ]
    elif edge_side == "west":
        candidates = [
            (edge_x - 1, edge_y),  # tile left of the edge
            (edge_x, edge_y),      # tile right of the edge
        ]
    else:
        return False

    for (tx, ty) in candidates:
        tile = level.tile_at(tx, ty)
        if tile is None:
            continue
        if tile.feature not in _OPEN_DOOR_FEATURES:
            continue
        if _door_side_suppresses_edge(
            tx, ty, tile.door_side,
            edge_x, edge_y, edge_side,
        ):
            return True
    return False


def edge_blocks_sight(
    level: Level, a: tuple[int, int], b: tuple[int, int],
) -> bool:
    """True when sight from ``a`` to ``b`` is blocked by an
    interior edge wall.

    Closed doors block via the tile-feature path (``tile.
    blocks_sight``); they're not treated as open here, so an edge
    behind a closed door still reads as walled.
    """
    edge = edge_between(a, b)
    if edge not in level.interior_edges:
        return False
    return not edge_has_open_door(level, *edge)


def edge_blocks_movement(
    level: Level, a: tuple[int, int], b: tuple[int, int],
) -> bool:
    """True when stepping from ``a`` to ``b`` is blocked by an
    interior edge wall.

    Orthogonal steps consult the single shared edge. Diagonal
    steps are blocked when EITHER of the two orthogonal legs
    crosses a walled edge — prevents the "squeeze through a
    corner" case.
    """
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if abs(dx) + abs(dy) == 1:
        edge = edge_between(a, b)
        if edge not in level.interior_edges:
            return False
        return not edge_has_open_door(level, *edge)
    if abs(dx) == 1 and abs(dy) == 1:
        # Diagonal: block if either orthogonal leg is walled.
        horiz = (ax + dx, ay)
        vert = (ax, ay + dy)
        return (
            edge_blocks_movement(level, a, horiz)
            or edge_blocks_movement(level, a, vert)
        )
    # Non-adjacent or zero step: no single edge applies.
    return False


def edge_shadow_tiles(
    level: Level, origin: tuple[int, int], radius: int,
) -> set[tuple[int, int]]:
    """Return the set of tiles within ``radius`` of ``origin``
    that are NOT reachable via a BFS respecting edge walls.

    Closed / locked doors block edges (their tile blocks sight
    separately via ``tile.blocks_sight``); open doors pass.

    Used as a shadow mask by the FOV pre-pass: a tile in the set
    is treated as blocking by the shadowcaster and subtracted
    from the final visible set so rooms behind a wall stay
    invisible.
    """
    reachable: set[tuple[int, int]] = {origin}
    frontier: deque[tuple[int, int, int]] = deque()
    frontier.append((origin[0], origin[1], 0))
    while frontier:
        x, y, dist = frontier.popleft()
        if dist >= radius:
            continue
        # Sight doesn't propagate through walls or closed doors.
        # The origin is exempt so a player standing on a closed
        # door still sees their own tile and neighbours. Without
        # this guard the BFS would happily walk along a perimeter
        # wall column to wrap around a partial interior edge wall
        # and light up the far room's floor tiles.
        if (x, y) != origin:
            tile = level.tile_at(x, y)
            if tile is not None and tile.blocks_sight:
                continue
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if not level.in_bounds(nx, ny):
                continue
            if (nx, ny) in reachable:
                continue
            if edge_blocks_sight(level, (x, y), (nx, ny)):
                continue
            reachable.add((nx, ny))
            frontier.append((nx, ny, dist + 1))

    # Tiles within the bounding box of radius that are NOT
    # reachable become shadowed. We only care about tiles close
    # enough that FOV could have seen them otherwise.
    shadow: set[tuple[int, int]] = set()
    ox, oy = origin
    for y in range(max(0, oy - radius), min(level.height, oy + radius + 1)):
        for x in range(
            max(0, ox - radius), min(level.width, ox + radius + 1),
        ):
            if (x, y) not in reachable:
                shadow.add((x, y))
    return shadow

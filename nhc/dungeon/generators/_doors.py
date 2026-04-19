"""Door candidate detection and door-side computation for BSP dungeons."""

from __future__ import annotations

import logging
from collections import defaultdict

from nhc.dungeon.model import (
    CircleShape,
    HybridShape,
    Level,
    PillShape,
    Rect,
    Room,
    RoomShape,
    RectShape,
    SurfaceType,
    TempleShape,
    Terrain,
)

logger = logging.getLogger(__name__)


def _hybrid_door_ok(
    room: Room, dx: int, dy: int, door_side: str,
) -> bool:
    """Return True if a door on a hybrid room is in a valid position.

    Doors in the circle half's range on the bounding rect edge
    must be at a cardinal wall position of the circle.  Doors on
    the rect half are always valid (already checked for straightness
    by the caller).
    """
    shape = room.shape
    if not isinstance(shape, HybridShape):
        return True
    circle_sub = None
    circle_side = ""
    for side, sub in [("left", shape.left), ("right", shape.right)]:
        if isinstance(sub, CircleShape):
            circle_sub = sub
            circle_side = side
            break
    if circle_sub is None:
        return True

    r = room.rect
    if shape.split == "vertical":
        mid = r.x + r.width // 2
        if circle_side == "left":
            c_rect = Rect(r.x, r.y, mid - r.x, r.height)
        else:
            c_rect = Rect(mid, r.y, r.x2 - mid, r.height)
        # Door on N/S edge: in circle range if column is in c_rect
        if dy == r.y - 1 or dy == r.y2:
            in_circle = c_rect.x <= dx < c_rect.x2
        # Door on E/W edge: in circle range if on circle's outer
        elif dx == r.x - 1:
            in_circle = c_rect.x == r.x
        elif dx == r.x2:
            in_circle = c_rect.x2 == r.x2
        else:
            in_circle = False
    else:
        mid = r.y + r.height // 2
        if circle_side == "left":
            c_rect = Rect(r.x, r.y, r.width, mid - r.y)
        else:
            c_rect = Rect(r.x, mid, r.width, r.y2 - mid)
        # Door on E/W edge: in circle range if row is in c_rect
        if dx == r.x - 1 or dx == r.x2:
            in_circle = c_rect.y <= dy < c_rect.y2
        # Door on N/S edge: in circle range if on circle's outer
        elif dy == r.y - 1:
            in_circle = c_rect.y == r.y
        elif dy == r.y2:
            in_circle = c_rect.y2 == r.y2
        else:
            in_circle = False

    if not in_circle:
        return True

    # Must be at a cardinal wall position
    if shape.split == "vertical":
        half = Rect(
            c_rect.x, c_rect.y,
            c_rect.width + 1, c_rect.height,
        )
    else:
        half = Rect(
            c_rect.x, c_rect.y,
            c_rect.width, c_rect.height + 1,
        )
    cardinals = circle_sub.cardinal_walls(half)
    return (dx, dy) in cardinals


def _door_candidates(
    room: Room,
) -> list[tuple[int, int, str]]:
    """Return valid door positions as (wall_x, wall_y, side) tuples.

    Uses a purely geometric approach based on the room's floor shape:

    1. Find perimeter floor tiles (floor with a non-floor cardinal
       neighbor). For each, record which edges face outward.
    2. Group co-linear perimeter edges into straight **wall runs**
       (e.g., all tiles on the north edge at the same y, forming
       a horizontal run).
    3. For each run of length >= 3, every position in the run
       (excluding the two endpoints) is a valid door candidate.
       The door sits on the wall tile one step outward from the
       perimeter floor tile.

    This approach works for any room shape and naturally avoids
    curved sections, diagonal transitions, and corners because
    those produce runs shorter than 3.
    """
    _OUTWARD = {
        "north": (0, -1),
        "south": (0, 1),
        "east": (1, 0),
        "west": (-1, 0),
    }

    floor = room.floor_tiles()

    # Step 1: find perimeter edges.
    # An edge is (floor_x, floor_y, side) where side indicates
    # the direction of the non-floor neighbor.
    edges: list[tuple[int, int, str]] = []
    for fx, fy in floor:
        for side, (dx, dy) in _OUTWARD.items():
            if (fx + dx, fy + dy) not in floor:
                edges.append((fx, fy, side))

    # Step 2: group edges into co-linear wall runs.
    # North/south edges group by (y, side) sorted by x.
    # East/west edges group by (x, side) sorted by y.
    h_runs: dict[tuple[int, str], list[int]] = defaultdict(list)
    v_runs: dict[tuple[int, str], list[int]] = defaultdict(list)

    for fx, fy, side in edges:
        if side in ("north", "south"):
            h_runs[(fy, side)].append(fx)
        else:
            v_runs[(fx, side)].append(fy)

    # Step 3: split into contiguous runs, then emit candidates.
    candidates: list[tuple[int, int, str]] = []

    def _contiguous_runs(vals: list[int]) -> list[list[int]]:
        """Split sorted values into contiguous sub-runs."""
        vals.sort()
        runs: list[list[int]] = []
        current: list[int] = [vals[0]]
        for v in vals[1:]:
            if v == current[-1] + 1:
                current.append(v)
            else:
                runs.append(current)
                current = [v]
        runs.append(current)
        return runs

    min_run = 2

    # Candidates produced by perimeter-run scanning must sit one step
    # outside the bounding rect.  Concave shapes (pill shoulders,
    # temple arm sides, cross inner walls) can form short straight
    # runs *inside* the rect where a door would damage the room
    # outline — reject those up front so corridor generation cannot
    # carve into the shoulder.  True cardinals for shapes that lack
    # long straight runs are injected below via cardinal_walls().
    r = room.rect

    def _on_rect_boundary(wx: int, wy: int) -> bool:
        return (
            wx == r.x - 1 or wx == r.x2
            or wy == r.y - 1 or wy == r.y2
        )

    for (fy, side), x_vals in h_runs.items():
        dx, dy = _OUTWARD[side]
        for run in _contiguous_runs(x_vals):
            if len(run) < min_run:
                continue
            # Exclude endpoints (they're at shape corners).
            # For runs of exactly min_run, include both.
            inner = run[1:-1] if len(run) > min_run else run
            for fx in inner:
                wx, wy = fx + dx, fy + dy
                if _on_rect_boundary(wx, wy):
                    candidates.append((wx, wy, side))

    for (fx, side), y_vals in v_runs.items():
        dx, dy = _OUTWARD[side]
        for run in _contiguous_runs(y_vals):
            if len(run) < min_run:
                continue
            inner = run[1:-1] if len(run) > min_run else run
            for fy in inner:
                wx, wy = fx + dx, fy + dy
                if _on_rect_boundary(wx, wy):
                    candidates.append((wx, wy, side))

    # For circles, pills, and temples, ensure the cardinal wall
    # positions are always included.  These shapes have curved or
    # pointed arm tips whose perimeter runs are too short for the
    # generic min_run filter; inject cardinals that aren't already
    # present.
    if isinstance(room.shape, (CircleShape, PillShape, TempleShape)):
        cand_set = {(x, y) for x, y, _ in candidates}
        _SIDE_FOR_DIR = {
            (0, -1): "north",
            (0, 1): "south",
            (-1, 0): "west",
            (1, 0): "east",
        }
        for wx, wy in room.shape.cardinal_walls(room.rect):
            if (wx, wy) not in cand_set:
                cx, cy = room.rect.center
                dx, dy = wx - cx, wy - cy
                # Normalise to unit cardinal direction
                if dx != 0:
                    dx = dx // abs(dx)
                if dy != 0:
                    dy = dy // abs(dy)
                side = _SIDE_FOR_DIR.get((dx, dy), "north")
                candidates.append((wx, wy, side))

    return candidates


def _compute_door_sides(level: Level) -> None:
    """Set door_side for every door tile.

    For each door, find the adjacent room-interior floor tile to
    determine which direction the door faces. The primary path
    consults ``level.rooms`` so a door wedged between a room and
    a corridor picks the room side. Building ground floors do not
    populate ``Room`` objects -- they are single-room interiors --
    so the fallback searches for any ``Terrain.FLOOR`` neighbour
    and uses its direction. Only if no floor neighbour exists does
    the final fallback consult wall/void, picking the side with
    the most continuous wall run so the door reads as sitting in
    that wall.
    """
    door_feats = {
        "door_closed", "door_open", "door_secret", "door_locked",
    }
    # Build floor→room lookup for all rooms
    floor_to_room: dict[tuple[int, int], Room] = {}
    for room in level.rooms:
        for pos in room.floor_tiles():
            floor_to_room[pos] = room

    # Map: if room floor is in direction (dx,dy) from door,
    # door_side is that direction name (pointing at the floor).
    _DIR = {
        (0, -1): "north",   # floor is north → door faces north
        (0, 1): "south",
        (1, 0): "east",
        (-1, 0): "west",
    }

    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in door_feats:
                continue
            # 1. Prefer a Room's floor tile.
            matched = False
            for (dx, dy), side in _DIR.items():
                if (x + dx, y + dy) in floor_to_room:
                    tile.door_side = side
                    matched = True
                    break
            if matched:
                continue
            # 2. No Rooms: accept any FLOOR neighbour so building
            #    interiors (single-room spaces with no Room objects
            #    attached) still get the interior direction.
            for (dx, dy), side in _DIR.items():
                nb = level.tile_at(x + dx, y + dy)
                if nb and nb.terrain == Terrain.FLOOR:
                    tile.door_side = side
                    matched = True
                    break
            if matched:
                continue
            # 3. Degenerate: pick the wall/void side as a last
            #    resort. The door will still render somewhere; the
            #    primary caller should avoid this branch.
            for (dx, dy), side in _DIR.items():
                nb = level.tile_at(x + dx, y + dy)
                if nb and nb.terrain in (
                    Terrain.WALL, Terrain.VOID,
                ):
                    tile.door_side = side
                    break


def _remove_non_straight_doors(level: Level) -> None:
    """Remove doors on curved or diagonal wall sections.

    A door sits on a straight wall when the adjacent room floor
    tile has floor neighbors on both sides along the wall
    direction (indicating a straight run of floor, not a corner
    or curve).  Doors that fail this check — arcs, octagon
    diagonals, cross indentations — are converted to plain
    corridor floor tiles so the corridor opens directly into
    the room.
    """
    door_feats = {
        "door_closed", "door_open", "door_secret", "door_locked",
    }
    # Direction toward room floor for each door_side
    _ROOM_DIR = {
        "north": (0, -1),
        "south": (0, 1),
        "east":  (1, 0),
        "west":  (-1, 0),
    }
    # Wall-parallel offsets to check along the floor run
    _WALL_PARALLEL = {
        "north": [(-1, 0), (1, 0)],
        "south": [(-1, 0), (1, 0)],
        "east":  [(0, -1), (0, 1)],
        "west":  [(0, -1), (0, 1)],
    }

    # Map floor positions to their room for non-rect rooms.
    floor_to_room: dict[tuple[int, int], Room] = {}
    for room in level.rooms:
        if isinstance(room.shape, RectShape):
            continue
        for pos in room.floor_tiles():
            floor_to_room[pos] = room

    removed = 0
    for y in range(level.height):
        for x in range(level.width):
            tile = level.tiles[y][x]
            if tile.feature not in door_feats:
                continue
            if not tile.door_side:
                continue
            # Find the room floor tile adjacent to this door
            rdx, rdy = _ROOM_DIR[tile.door_side]
            floor_pos = (x + rdx, y + rdy)
            room = floor_to_room.get(floor_pos)
            if room is None:
                continue  # rect room — keep door

            # A door on the bounding rect's edge is straight
            # when the floor reaches that edge at the door's
            # row/column.  This keeps doors on flat sides of
            # octagons, rect halves of hybrids, and cross arms
            # while removing them at curves and diagonals.
            r = room.rect
            fx, fy = floor_pos
            floor_tiles = room.floor_tiles()
            straight = True
            # A door is on a straight wall when the room
            # outline runs parallel to the rect boundary at
            # the door position.  This holds when the floor
            # reaches the rect edge AND enough floor tiles
            # span the wall direction (≥3 tiles in a row
            # along the rect edge) — indicating a flat side,
            # not a narrow tip or diagonal.
            if tile.door_side in ("east", "west"):
                edge_x = r.x if tile.door_side == "east" \
                    else r.x2 - 1
                if fx != edge_x:
                    straight = False
                else:
                    # Count floor tiles along Y at this column
                    span = sum(
                        1 for yy in range(r.y, r.y2)
                        if (edge_x, yy) in floor_tiles
                    )
                    straight = span >= 3
            else:
                edge_y = r.y if tile.door_side == "south" \
                    else r.y2 - 1
                if fy != edge_y:
                    straight = False
                else:
                    span = sum(
                        1 for xx in range(r.x, r.x2)
                        if (xx, edge_y) in floor_tiles
                    )
                    straight = span >= 3
            # For hybrid rooms, even a "straight" span can be
            # invalid if the door sits in the circle half's
            # range — diagonal transition tiles inflate the
            # span but the wall is curved there.
            if straight and isinstance(room.shape, HybridShape):
                straight = _hybrid_door_ok(
                    room, x, y, tile.door_side,
                )

            if not straight:
                tile.feature = None
                tile.surface_type = SurfaceType.CORRIDOR
                tile.door_side = ""
                removed += 1
    if removed:
        logger.info("Removed %d doors on non-straight walls", removed)

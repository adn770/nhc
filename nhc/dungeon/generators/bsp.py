"""BSP (Binary Space Partitioning) dungeon generator.

Recursively subdivides the map into regions, places rooms within each
leaf, then connects them via corridors with main path + extra loops.
"""

from __future__ import annotations

import logging
import random
from collections import deque
from dataclasses import dataclass

from nhc.dungeon.generator import DungeonGenerator, GenerationParams

logger = logging.getLogger(__name__)
from nhc.dungeon.model import (
    CircleShape,
    Corridor,
    CrossShape,
    HybridShape,
    Level,
    LevelMetadata,
    OctagonShape,
    Rect,
    RectShape,
    Room,
    RoomShape,
    Terrain,
    Tile,
)
from nhc.utils.rng import get_rng

MIN_LEAF = 9
MAX_ROOM = 10
MIN_ROOM = 4
PADDING = 2  # ≥2 ensures void gap between adjacent rooms' walls


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
    from collections import defaultdict
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

    for (fy, side), x_vals in h_runs.items():
        dx, dy = _OUTWARD[side]
        for run in _contiguous_runs(x_vals):
            if len(run) < min_run:
                continue
            # Exclude endpoints (they're at shape corners).
            # For runs of exactly min_run, include both.
            inner = run[1:-1] if len(run) > min_run else run
            for fx in inner:
                candidates.append((fx + dx, fy + dy, side))

    for (fx, side), y_vals in v_runs.items():
        dx, dy = _OUTWARD[side]
        for run in _contiguous_runs(y_vals):
            if len(run) < min_run:
                continue
            inner = run[1:-1] if len(run) > min_run else run
            for fy in inner:
                candidates.append((fx + dx, fy + dy, side))

    # For circles, ensure the 4 cardinal wall positions are always
    # included.  Small circles produce only length-1 perimeter runs
    # (every edge changes x), so the generic min_run filter drops
    # them all.  Inject cardinals that aren't already present.
    if isinstance(room.shape, CircleShape):
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


# ── BSP tree ────────────────────────────────────────────────────────

@dataclass
class _Node:
    rect: Rect
    left: _Node | None = None
    right: _Node | None = None
    room: Rect | None = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def leaves(self) -> list[_Node]:
        if self.is_leaf:
            return [self]
        out: list[_Node] = []
        if self.left:
            out += self.left.leaves()
        if self.right:
            out += self.right.leaves()
        return out


def _split(node: _Node, rng: random.Random) -> None:
    """Recursively split a BSP node."""
    w, h = node.rect.width, node.rect.height
    if w < MIN_LEAF * 2 and h < MIN_LEAF * 2:
        return

    if w > h * 1.25:
        horiz = False
    elif h > w * 1.25:
        horiz = True
    else:
        horiz = rng.random() < 0.5

    if horiz:
        if h < MIN_LEAF * 2:
            return
        at = rng.randint(MIN_LEAF, h - MIN_LEAF)
        node.left = _Node(Rect(node.rect.x, node.rect.y, w, at))
        node.right = _Node(Rect(node.rect.x, node.rect.y + at, w, h - at))
    else:
        if w < MIN_LEAF * 2:
            return
        at = rng.randint(MIN_LEAF, w - MIN_LEAF)
        node.left = _Node(Rect(node.rect.x, node.rect.y, at, h))
        node.right = _Node(Rect(node.rect.x + at, node.rect.y, w - at, h))

    _split(node.left, rng)
    _split(node.right, rng)


def _place_room(leaf: _Node, rng: random.Random) -> None:
    """Place a random room inside a BSP leaf."""
    mw = min(MAX_ROOM, leaf.rect.width - PADDING * 2)
    mh = min(MAX_ROOM, leaf.rect.height - PADDING * 2)
    if mw < MIN_ROOM or mh < MIN_ROOM:
        return
    w = rng.randint(MIN_ROOM, mw)
    h = rng.randint(MIN_ROOM, mh)
    x = leaf.rect.x + rng.randint(PADDING, leaf.rect.width - w - PADDING)
    y = leaf.rect.y + rng.randint(PADDING, leaf.rect.height - h - PADDING)
    leaf.room = Rect(x, y, w, h)


# ── Connectivity ────────────────────────────────────────────────────

def _center_dist(a: Rect, b: Rect) -> int:
    """Manhattan distance between room centers."""
    ax, ay = a.center
    bx, by = b.center
    return abs(ax - bx) + abs(ay - by)


def _find_neighbors(rects: list[Rect], max_dist: int = 25) -> list[tuple[int, int]]:
    """Find room pairs close enough to connect (by center distance)."""
    pairs: list[tuple[int, int]] = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if _center_dist(rects[i], rects[j]) <= max_dist:
                pairs.append((i, j))
    return pairs


def _bfs(adj: dict[int, set[int]], start: int, end: int) -> list[int] | None:
    visited: set[int] = {start}
    queue: deque[list[int]] = deque([[start]])
    while queue:
        path = queue.popleft()
        if path[-1] == end:
            return path
        for nb in adj.get(path[-1], set()):
            if nb not in visited:
                visited.add(nb)
                queue.append(path + [nb])
    return None


def _bfs_dist(adj: dict[int, set[int]], start: int) -> dict[int, int]:
    """BFS distances from start to all reachable nodes."""
    dist: dict[int, int] = {start: 0}
    queue: deque[int] = deque([start])
    while queue:
        node = queue.popleft()
        for nb in adj.get(node, set()):
            if nb not in dist:
                dist[nb] = dist[node] + 1
                queue.append(nb)
    return dist


# ── Generator ───────────────────────────────────────────────────────

class BSPGenerator(DungeonGenerator):
    """Generate dungeons using BSP room subdivision."""

    def generate(
        self, params: GenerationParams,
        rng: "random.Random | None" = None,
    ) -> Level:
        rng = rng or get_rng()
        logger.info(
            "BSP generate: %dx%d depth=%d theme=%s",
            params.width, params.height, params.depth, params.theme,
        )
        level = Level.create_empty(
            id=f"depth_{params.depth}",
            name=f"Dungeon Level {params.depth}",
            depth=params.depth,
            width=params.width,
            height=params.height,
        )
        level.metadata = LevelMetadata(
            theme=params.theme, difficulty=params.depth,
        )

        # ── 1. BSP subdivision ──
        root = _Node(Rect(1, 1, params.width - 2, params.height - 2))
        _split(root, rng)
        leaves = root.leaves()
        for leaf in leaves:
            _place_room(leaf, rng)

        rects = [lf.room for lf in leaves if lf.room]
        logger.info(
            "BSP split: %d leaves, %d rooms placed",
            len(leaves), len(rects),
        )
        if len(rects) < 3:
            logger.warning("BSP produced <3 rooms, falling back to classic")
            from nhc.dungeon.classic import ClassicGenerator
            return ClassicGenerator().generate(params)

        # ── Step 1: Carve rooms ──
        shapes = [
            self._pick_shape(rect, params.shape_variety, rng)
            for rect in rects
        ]
        for rect, shape in zip(rects, shapes):
            self._carve_room(level, rect, shape)
        for i, (rect, shape) in enumerate(zip(rects, shapes)):
            level.rooms.append(
                Room(id=f"room_{i + 1}", rect=rect, shape=shape),
            )
            logger.debug(
                "Room %d: (%d,%d) %dx%d",
                i + 1, rect.x, rect.y, rect.width, rect.height,
            )

        # ── Step 2: Build walls around rooms ──
        self._build_walls(level)

        # ── Step 3: Connectivity — carve corridors through VOID ──
        neighbors = _find_neighbors(rects)
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for i, j in neighbors:
            adj[i].add(j)
            adj[j].add(i)
        logger.info("Neighbor pairs found: %d", len(neighbors))

        entrance = 0
        dists = _bfs_dist(adj, entrance)
        exit_idx = max(dists, key=dists.get) if dists else len(rects) - 1
        logger.info(
            "Entrance: room_%d (%d,%d)  Exit: room_%d (%d,%d)  "
            "path distance: %d",
            entrance + 1, *rects[entrance].center,
            exit_idx + 1, *rects[exit_idx].center,
            dists.get(exit_idx, -1),
        )

        # Main path
        connected: set[tuple[int, int]] = set()
        main_path = _bfs(adj, entrance, exit_idx)
        if main_path:
            logger.info("Main path: %d rooms", len(main_path))
            for k in range(len(main_path) - 1):
                a, b = main_path[k], main_path[k + 1]
                pair = (min(a, b), max(a, b))
                connected.add(pair)
                self._carve_corridor(
                    level, level.rooms[a], level.rooms[b], rng,
                )
        else:
            logger.warning("No main path found between entrance and exit")

        # Extra loops
        extra = 0
        for i, j in neighbors:
            pair = (min(i, j), max(i, j))
            if pair not in connected and rng.random() < params.connectivity * 0.5:
                connected.add(pair)
                self._carve_corridor(
                    level, level.rooms[i], level.rooms[j], rng,
                )
                extra += 1
        logger.info("Extra loop corridors: %d", extra)

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
                    self._carve_corridor(
                        level, level.rooms[idx], level.rooms[best_other],
                        rng,
                    )
                    logger.info(
                        "Connected isolated room_%d to room_%d (dist=%d)",
                        idx + 1, best_other + 1, best_dist,
                    )
                    changed = True
                    break

        for ci, (a, b) in enumerate(connected):
            level.corridors.append(Corridor(
                id=f"corridor_{ci}",
                connects=[level.rooms[a].id, level.rooms[b].id],
            ))

        # ── Step 3b: Prune dead-end corridor stubs ──
        # L-shaped corridors can leave dead stubs at bend points.
        # Iteratively remove corridor tiles with ≤1 floor neighbor
        # until no more dead ends remain.
        def _adjacent_to_door(ax: int, ay: int) -> bool:
            """True if any cardinal neighbor is a door."""
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = level.tile_at(ax + ddx, ay + ddy)
                if nb and nb.feature in (
                    "door_closed", "door_open", "door_secret",
                    "door_locked",
                ):
                    return True
            return False

        pruned = True
        while pruned:
            pruned = False
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if not (tile.terrain == Terrain.FLOOR
                            and tile.is_corridor
                            and not tile.feature):
                        continue
                    # Never prune corridor tiles next to doors
                    if _adjacent_to_door(x, y):
                        continue
                    floor_neighbors = 0
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.terrain == Terrain.FLOOR:
                            floor_neighbors += 1
                    if floor_neighbors <= 1:
                        level.tiles[y][x] = Tile(terrain=Terrain.VOID)
                        pruned = True

        # ── Step 3b: Handle dead-end corridor stubs ──
        # L-shaped corridors can leave dead stubs at bend points.
        # For each dead end: 30% add secret door if wall adjacent,
        # 30% keep as atmospheric dead end, 40% prune.
        changed = True
        while changed:
            changed = False
            for y in range(level.height):
                for x in range(level.width):
                    tile = level.tiles[y][x]
                    if not (tile.terrain == Terrain.FLOOR
                            and tile.is_corridor
                            and not tile.feature):
                        continue
                    # Never prune corridor tiles next to doors
                    if _adjacent_to_door(x, y):
                        continue
                    floor_neighbors = 0
                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.terrain == Terrain.FLOOR:
                            floor_neighbors += 1
                    if floor_neighbors > 1:
                        continue
                    # Dead end found
                    roll = rng.random()
                    if roll < 0.3:
                        # Try to place a secret door on adjacent wall
                        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                            nb = level.tile_at(x + dx, y + dy)
                            if nb and nb.terrain == Terrain.WALL:
                                nb.terrain = Terrain.FLOOR
                                nb.feature = "door_secret"
                                break
                        # Keep the corridor tile
                    elif roll < 0.6:
                        pass  # Keep as dead end
                    else:
                        # Prune
                        level.tiles[y][x] = Tile(terrain=Terrain.VOID)
                        changed = True

        # ── Step 3c: Remove orphaned doors ──
        # After pruning, some doors may have no corridor/floor on the
        # non-room side.  Revert those back to plain walls.
        door_features = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.feature not in door_features:
                    continue
                # Find which room this door belongs to (adjacent floor
                # that is NOT a corridor)
                has_room_side = False
                has_corridor_side = False
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if not nb:
                        continue
                    if nb.terrain == Terrain.FLOOR and not nb.is_corridor:
                        has_room_side = True
                    if nb.terrain == Terrain.FLOOR and nb.is_corridor:
                        has_corridor_side = True
                if has_room_side and not has_corridor_side:
                    # Door leads nowhere — revert to wall
                    level.tiles[y][x] = Tile(terrain=Terrain.WALL)
                    logger.debug(
                        "Removed orphaned door at (%d, %d)", x, y,
                    )

        all_door_feats = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }

        # ── Step 3d: Verify connectivity via flood fill ──
        # After all pruning and cleanup, verify every room is reachable
        # from the entrance via walkable tiles.  If not, re-carve.
        def _flood_reachable(sx: int, sy: int) -> set[tuple[int, int]]:
            """Flood-fill from (sx,sy) across FLOOR tiles."""
            visited: set[tuple[int, int]] = set()
            stack = [(sx, sy)]
            while stack:
                fx, fy = stack.pop()
                if (fx, fy) in visited:
                    continue
                ft = level.tile_at(fx, fy)
                if not ft or ft.terrain != Terrain.FLOOR:
                    continue
                visited.add((fx, fy))
                for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    stack.append((fx + ddx, fy + ddy))
            return visited

        ecx, ecy = rects[entrance].center
        reconnected = 0
        for _attempt in range(len(rects)):
            reachable = _flood_reachable(ecx, ecy)
            found_disconnect = False
            for ri, rect in enumerate(rects):
                rcx, rcy = rect.center
                if (rcx, rcy) in reachable:
                    continue
                found_disconnect = True
                # Room is disconnected — find closest reachable room
                best_other = None
                best_dist = 9999
                for oi, orect in enumerate(rects):
                    ocx, ocy = orect.center
                    if (ocx, ocy) not in reachable:
                        continue
                    d = abs(rcx - ocx) + abs(rcy - ocy)
                    if d < best_dist:
                        best_dist = d
                        best_other = oi
                if best_other is not None:
                    # Use force=True on _carve_line to punch through
                    # any walls in the path
                    self._carve_corridor_force(
                        level, level.rooms[ri], level.rooms[best_other],
                        rng,
                    )
                    reconnected += 1
                    logger.info(
                        "Reconnected room_%d to room_%d (flood-fill)",
                        ri + 1, best_other + 1,
                    )
                break  # Re-check from scratch after each reconnection
            if not found_disconnect:
                break

        if reconnected:
            logger.info("Post-prune reconnection: %d corridors added",
                        reconnected)

        # ── Step 3e: Final door harmonization ──
        # Reconnection (3d) may have added new doors adjacent to
        # existing ones.  One final pass to unify types.
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.feature not in all_door_feats:
                    continue
                for ddx, ddy in [(1, 0), (0, 1)]:
                    nb = level.tile_at(x + ddx, y + ddy)
                    if nb and nb.feature in all_door_feats:
                        if nb.feature != tile.feature:
                            nb.feature = tile.feature

        # ── Step 4: Stairs ──
        self._place_stairs(level, rects, adj, rng)

        # Compute door_side for all door tiles
        self._compute_door_sides(level)

        # Remove doors on non-straight wall sections (arcs, diagonals)
        self._remove_non_straight_doors(level)

        doors = sum(1 for row in level.tiles for t in row
                    if t.feature and "door" in t.feature)
        secrets = sum(1 for row in level.tiles for t in row
                      if t.feature == "door_secret")
        corridors_total = sum(1 for row in level.tiles for t in row
                              if t.is_corridor)
        logger.info(
            "Generation complete: %d rooms, %d corridors, %d doors "
            "(%d secret), %d corridor tiles",
            len(level.rooms), len(connected), doors, secrets,
            corridors_total,
        )

        return level

    @staticmethod
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

        # Pick entry room randomly
        entry = rng.randrange(n)
        dists = _bfs_dist(adj, entry)
        max_dist = max(dists.values()) if dists else 1

        # Candidates for stairs_down: at least half max distance
        min_dist = max(1, max_dist // 2)
        candidates = [
            i for i, d in dists.items()
            if d >= min_dist and i != entry
        ]
        if not candidates:
            # Fallback: any room except entry
            candidates = [i for i in range(n) if i != entry]

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

    @staticmethod
    def _compute_door_sides(level: Level) -> None:
        """Set door_side for every door tile.

        For each door, find the adjacent room floor tile to determine
        which direction the door faces (toward the room interior).
        Works for any room shape, not just rectangles.
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
        # door_side is the opposite direction name
        _OPPOSITE = {
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
                # Find adjacent room floor tile
                for (dx, dy), side in _OPPOSITE.items():
                    if (x + dx, y + dy) in floor_to_room:
                        tile.door_side = side
                        break
                else:
                    # Fallback: find adjacent wall/void
                    for side, dx, dy in [
                        ("north", 0, -1), ("south", 0, 1),
                        ("east", 1, 0), ("west", -1, 0),
                    ]:
                        nb = level.tile_at(x + dx, y + dy)
                        if nb and nb.terrain in (
                            Terrain.WALL, Terrain.VOID,
                        ):
                            tile.door_side = side
                            break

    @staticmethod
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
                    tile.is_corridor = True
                    tile.door_side = ""
                    removed += 1
        if removed:
            logger.info("Removed %d doors on non-straight walls", removed)

    # ── Carving helpers ─────────────────────────────────────────────

    def _build_walls(self, level: Level) -> None:
        """Place WALL tiles around room floors only (not corridors).

        Corridors have VOID on their sides — they're narrow passages
        through darkness, not walled tunnels.  Only non-corridor
        FLOOR and WATER tiles get surrounding walls (8-neighbor).
        """
        walkable = {Terrain.FLOOR, Terrain.WATER}
        to_wall: set[tuple[int, int]] = set()

        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                # Only build walls around room tiles, not corridors
                if tile.terrain not in walkable or tile.is_corridor:
                    continue
                for dy in range(-1, 2):
                    for dx in range(-1, 2):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if (level.in_bounds(nx, ny)
                                and level.tiles[ny][nx].terrain
                                == Terrain.VOID):
                            to_wall.add((nx, ny))

        for wx, wy in to_wall:
            level.tiles[wy][wx] = Tile(terrain=Terrain.WALL)

    @staticmethod
    def _pick_shape(
        rect: Rect, variety: float, rng: random.Random,
    ) -> RoomShape:
        """Choose a room shape based on variety setting and rect size."""
        if variety <= 0 or rng.random() >= variety:
            return RectShape()
        min_dim = min(rect.width, rect.height)
        max_dim = max(rect.width, rect.height)

        if min_dim < 5:
            return RectShape()

        # Hybrids: half-circle + rect. Split along the longer axis
        # so the circle half is near-square.  The half that receives
        # the circle must have an odd dimension for clean cardinal
        # points (CircleShape enforces odd diameter internally).
        if max_dim >= 7 and rng.random() < 0.20:
            if rect.width >= rect.height:
                split = "vertical"
            else:
                split = "horizontal"
            return HybridShape(CircleShape(), RectShape(), split)

        # Collect eligible shapes for this room size
        candidates: list[type[RoomShape]] = [
            OctagonShape, CrossShape,
        ]
        # Circles only for near-square rooms where both dimensions
        # are odd (ensures integer center and clean cardinal points)
        if (max_dim / min_dim <= 1.3
                and rect.width % 2 == 1 and rect.height % 2 == 1):
            candidates.append(CircleShape)

        return rng.choice(candidates)()

    def _carve_room(self, level: Level, rect: Rect,
                    shape: RoomShape | None = None) -> None:
        tiles = (shape or RectShape()).floor_tiles(rect)
        for x, y in tiles:
            if level.in_bounds(x, y):
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    def _wall_entry(
        self, level: Level, room: Room, tx: int, ty: int,
    ) -> tuple[int, int]:
        """Find a wall tile adjacent to *room* facing (tx, ty).

        Uses _door_candidates() to get geometrically valid positions,
        then scores them by facing direction and distance to target.
        """
        cx, cy = room.rect.center
        dx, dy = tx - cx, ty - cy

        cands = _door_candidates(room)
        if not cands:
            return cx, cy

        scored: list[tuple[int, int, float]] = []
        for wx, wy, side in cands:
            wdx, wdy = wx - cx, wy - cy
            facing = wdx * dx + wdy * dy
            dist = abs(wx - tx) + abs(wy - ty)
            score = -facing * 1000 + dist
            scored.append((wx, wy, score))

        scored.sort(key=lambda c: c[2])
        return scored[0][0], scored[0][1]

    @staticmethod
    def _outward(room: Room, wx: int, wy: int) -> tuple[int, int]:
        """Step one tile away from *room* starting from wall (wx, wy).

        Finds which cardinal direction leads away from the room's
        floor tiles and returns the first VOID-side position.
        Works for any room shape.
        """
        floor = room.floor_tiles()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if (wx + dx, wy + dy) in floor:
                # Floor is in this direction; outward is opposite
                return wx - dx, wy - dy
        # Fallback: use bounding rect logic
        r = room.rect
        if wx < r.x:
            return wx - 1, wy
        if wx >= r.x2:
            return wx + 1, wy
        if wy < r.y:
            return wx, wy - 1
        if wy >= r.y2:
            return wx, wy + 1
        return wx, wy

    def _carve_corridor(
        self, level: Level, a: Room, b: Room, rng: random.Random,
    ) -> None:
        """Connect two rooms by carving through VOID only.

        1. Find wall entry on each room facing the other.
        2. Convert each wall entry to a door.
        3. Step one tile outside into VOID.
        4. Carve an L-shaped path through VOID between those points.
        """
        bx, by = b.rect.center
        ax, ay = a.rect.center

        # Wall entries
        wa_x, wa_y = self._wall_entry(level, a, bx, by)
        wb_x, wb_y = self._wall_entry(level, b, ax, ay)

        # Convert wall entries to doors
        # 10% secret, 5-15% locked (scales with depth), rest normal
        roll = rng.random()
        depth = getattr(level, "depth", 1)
        lock_chance = 0.05 + depth * 0.02  # 7% at depth 1, 15% at depth 5
        if roll < 0.1:
            feat = "door_secret"
        elif roll < 0.1 + lock_chance:
            feat = "door_locked"
        else:
            feat = "door_closed"

        door_feats = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }
        for wx, wy in [(wa_x, wa_y), (wb_x, wb_y)]:
            t = level.tile_at(wx, wy)
            if t and t.terrain == Terrain.WALL:
                adj_feat = None
                for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(wx + ddx, wy + ddy)
                    if nb and nb.feature in door_feats:
                        adj_feat = nb.feature
                        break
                level.tiles[wy][wx] = Tile(
                    terrain=Terrain.FLOOR,
                    feature=adj_feat if adj_feat else feat,
                )

        sx, sy = self._outward(a, wa_x, wa_y)
        ex, ey = self._outward(b, wb_x, wb_y)

        # Carve L-shaped corridor through VOID only
        if rng.random() < 0.5:
            self._carve_line(level, sx, sy, ex, sy)
            self._carve_line(level, ex, sy, ex, ey)
        else:
            self._carve_line(level, sx, sy, sx, ey)
            self._carve_line(level, sx, ey, ex, ey)

    def _carve_corridor_force(
        self, level: Level, a: Room, b: Room, rng: random.Random,
    ) -> None:
        """Connect two rooms, punching through walls if needed.

        Same as _carve_corridor but uses force=True on _carve_line
        to guarantee the corridor actually connects even if walls
        from other rooms are in the path.
        """
        bx, by = b.rect.center
        ax, ay = a.rect.center

        wa_x, wa_y = self._wall_entry(level, a, bx, by)
        wb_x, wb_y = self._wall_entry(level, b, ax, ay)

        for wx, wy in [(wa_x, wa_y), (wb_x, wb_y)]:
            t = level.tile_at(wx, wy)
            if t and t.terrain == Terrain.WALL:
                level.tiles[wy][wx] = Tile(
                    terrain=Terrain.FLOOR, feature="door_closed",
                )

        sx, sy = self._outward(a, wa_x, wa_y)
        ex, ey = self._outward(b, wb_x, wb_y)

        if rng.random() < 0.5:
            self._carve_line(level, sx, sy, ex, sy, force=True)
            self._carve_line(level, ex, sy, ex, ey, force=True)
        else:
            self._carve_line(level, sx, sy, sx, ey, force=True)
            self._carve_line(level, sx, ey, ex, ey, force=True)

    def _carve_line(
        self, level: Level, x1: int, y1: int, x2: int, y2: int,
        force: bool = False,
    ) -> None:
        """Carve a straight corridor line.

        Normally only replaces VOID tiles.  When *force* is True,
        also carves through WALL tiles (placing a door at each
        wall crossing) to guarantee connectivity.
        """
        def _carve_tile(cx: int, cy: int) -> None:
            if not level.in_bounds(cx, cy):
                return
            t = level.tiles[cy][cx]
            if t.terrain == Terrain.VOID:
                level.tiles[cy][cx] = Tile(
                    terrain=Terrain.FLOOR, is_corridor=True,
                )
            elif force and t.terrain == Terrain.WALL:
                level.tiles[cy][cx] = Tile(
                    terrain=Terrain.FLOOR, feature="door_closed",
                )

        if y1 == y2:
            for x in range(min(x1, x2), max(x1, x2) + 1):
                _carve_tile(x, y1)
        else:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                _carve_tile(x1, y)

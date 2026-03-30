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
    Level,
    LevelMetadata,
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

    def generate(self, params: GenerationParams) -> Level:
        rng = get_rng()
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
        sx, sy = rects[entrance].center
        level.tiles[sy][sx].feature = "stairs_up"
        ex, ey = rects[exit_idx].center
        level.tiles[ey][ex].feature = "stairs_down"
        level.rooms[entrance].tags.append("entry")
        level.rooms[exit_idx].tags.append("exit")

        # Compute door_side for all door tiles
        self._compute_door_sides(level)

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
        # Circles need at least 5x5 to look reasonable
        if min(rect.width, rect.height) >= 5:
            return CircleShape()
        return RectShape()

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

        Scans all WALL tiles adjacent to the room's floor tiles,
        filters out corners and tiles next to existing doors, then
        picks the best candidate on the facing side.
        Works for any room shape.
        """
        cx, cy = room.rect.center
        dx, dy = tx - cx, ty - cy
        floor = room.floor_tiles()

        _DOOR_FEATURES = {
            "door_closed", "door_open", "door_secret", "door_locked",
        }

        def _has_adjacent_door(wx: int, wy: int) -> bool:
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = level.tile_at(wx + ddx, wy + ddy)
                if nb and nb.feature in _DOOR_FEATURES:
                    return True
            return False

        def _is_convex_corner(wx: int, wy: int) -> bool:
            """True if this wall is at a convex corner of the room.

            A convex corner has floor neighbors in exactly two
            perpendicular cardinal directions and no floor on the
            diagonal between them. Doors placed here break corridor
            carving. Tiles with 0 floor neighbors are also excluded
            (isolated wall, shouldn't be a door entry).
            """
            adj_floor = sum(
                1 for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                if (wx + ddx, wy + ddy) in floor
            )
            return adj_floor == 0

        # Collect all WALL tiles adjacent to room floor
        perimeter_walls: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for fx, fy in floor:
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = fx + ddx, fy + ddy
                if (nx, ny) in seen or (nx, ny) in floor:
                    continue
                seen.add((nx, ny))
                t = level.tile_at(nx, ny)
                if t and t.terrain == Terrain.WALL:
                    perimeter_walls.append((nx, ny))

        # Prefer walls on the facing side (same direction as target)
        # Score: distance to target, with a penalty for wrong-side
        cands: list[tuple[int, int, float]] = []
        for wx, wy in perimeter_walls:
            if _is_convex_corner(wx, wy):
                continue
            if _has_adjacent_door(wx, wy):
                continue
            # Direction from room center to this wall
            wdx, wdy = wx - cx, wy - cy
            # Facing bonus: dot product with target direction
            facing = (wdx * dx + wdy * dy)
            dist = abs(wx - tx) + abs(wy - ty)
            # Prefer walls that face the target (high facing score)
            # Break ties by proximity to target
            score = -facing * 1000 + dist
            cands.append((wx, wy, score))

        if not cands:
            return cx, cy
        cands.sort(key=lambda c: c[2])
        return cands[0][0], cands[0][1]

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

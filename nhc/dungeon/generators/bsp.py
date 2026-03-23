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
    Corridor,
    Level,
    LevelMetadata,
    Rect,
    Room,
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

        # Carve rooms
        for rect in rects:
            self._carve_room(level, rect)
        for i, rect in enumerate(rects):
            level.rooms.append(Room(id=f"room_{i + 1}", rect=rect))
            logger.debug(
                "Room %d: (%d,%d) %dx%d",
                i + 1, rect.x, rect.y, rect.width, rect.height,
            )

        # ── 2. Connectivity ──
        neighbors = _find_neighbors(rects)
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for i, j in neighbors:
            adj[i].add(j)
            adj[j].add(i)
        logger.info("Neighbor pairs found: %d", len(neighbors))

        # Pick entrance/exit (maximize distance)
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
                self._connect(level, rects[a], rects[b], rng)
        else:
            logger.warning("No main path found between entrance and exit")

        # Extra loops
        extra = 0
        for i, j in neighbors:
            pair = (min(i, j), max(i, j))
            if pair not in connected and rng.random() < params.connectivity * 0.5:
                connected.add(pair)
                self._connect(level, rects[i], rects[j], rng)
                extra += 1
        logger.info("Extra loop corridors: %d", extra)

        # Ensure full reachability — connect isolated rooms to the
        # nearest already-reachable room by center distance
        changed = True
        while changed:
            changed = False
            reachable = _bfs_dist(adj, entrance)
            for idx in range(len(rects)):
                if idx in reachable:
                    continue
                # Find nearest reachable room
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
                    self._connect(level, rects[idx], rects[best_other], rng)
                    logger.info(
                        "Connected isolated room_%d to room_%d (dist=%d)",
                        idx + 1, best_other + 1, best_dist,
                    )
                    changed = True
                    break  # Restart — new room is now reachable

        # Corridor metadata
        for ci, (a, b) in enumerate(connected):
            level.corridors.append(Corridor(
                id=f"corridor_{ci}",
                connects=[level.rooms[a].id, level.rooms[b].id],
            ))

        # ── 3. Stairs ──
        sx, sy = rects[entrance].center
        level.tiles[sy][sx].feature = "stairs_up"
        ex, ey = rects[exit_idx].center
        level.tiles[ey][ex].feature = "stairs_down"
        level.rooms[entrance].tags.append("entry")
        level.rooms[exit_idx].tags.append("exit")

        # ── 4. Build walls around room tiles ──
        self._build_walls(level)

        # ── 4b. Process walls and corridors adjacent to rooms ──
        # 1) Scan: classify every wall touching a corridor
        # 2) Apply: doors at junctions, void elsewhere
        # All changes collected before applying to avoid mutation bugs.

        to_door: list[tuple[int, int]] = []
        to_void: list[tuple[int, int]] = []

        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.terrain != Terrain.WALL:
                    continue
                has_corridor = False
                has_room = False
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if not nb or nb.terrain != Terrain.FLOOR:
                        continue
                    if nb.is_corridor:
                        has_corridor = True
                    else:
                        has_room = True
                if has_corridor and has_room:
                    to_door.append((x, y))
                elif has_corridor:
                    to_void.append((x, y))

        # Also find corridor tiles directly adjacent to room floor
        # (no wall between them)
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (tile.terrain == Terrain.FLOOR
                        and tile.is_corridor):
                    continue
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if (nb and nb.terrain == Terrain.FLOOR
                            and not nb.is_corridor):
                        to_door.append((x, y))
                        break

        # Apply doors first (deduplicate, skip adjacent)
        door_positions: set[tuple[int, int]] = set()
        for dx, dy in to_door:
            self._set_door(level, dx, dy, rng,
                           params.secret_doors, door_positions)

        # ── 4c. Final enforcement pass ──
        # Any corridor tile directly adjacent to room floor without a
        # door between them gets converted to a door.
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (tile.terrain == Terrain.FLOOR
                        and tile.is_corridor and not tile.feature):
                    continue
                for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + ddx, y + ddy)
                    if (nb and nb.terrain == Terrain.FLOOR
                            and not nb.is_corridor and not nb.feature):
                        self._set_door(level, x, y, rng,
                                       params.secret_doors, door_positions)
                        break

        # Final cleanup: any WALL touching a corridor must become VOID
        # (re-scan after door placement changed the topology)
        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if tile.terrain != Terrain.WALL:
                    continue
                for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + ddx, y + ddy)
                    if (nb and nb.terrain == Terrain.FLOOR
                            and nb.is_corridor):
                        # Wall touches corridor without room on other
                        # side → void
                        has_room = any(
                            level.tile_at(x + dx2, y + dy2)
                            and level.tile_at(x + dx2, y + dy2).terrain
                            == Terrain.FLOOR
                            and not level.tile_at(x + dx2, y + dy2).is_corridor
                            and not level.tile_at(x + dx2, y + dy2).feature
                            for dx2, dy2 in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                            if (dx2, dy2) != (ddx, ddy)
                        )
                        if not has_room:
                            level.tiles[y][x] = Tile(terrain=Terrain.VOID)
                        break

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

    def _carve_room(self, level: Level, rect: Rect) -> None:
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                if level.in_bounds(x, y):
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    def _find_entry_point(
        self, level: Level, rect: Rect, target_x: int, target_y: int,
    ) -> tuple[int, int]:
        """Find the best wall-entry point on a room facing the target.

        Returns a position on the room's border (not a corner) closest
        to the target direction.
        """
        cx, cy = rect.center
        dx = target_x - cx
        dy = target_y - cy

        candidates: list[tuple[int, int, int]] = []  # (x, y, dist)

        if abs(dx) >= abs(dy):
            # Primarily horizontal — pick from east or west wall
            wall_x = rect.x2 - 1 if dx > 0 else rect.x
            for wy in range(rect.y + 1, rect.y2 - 1):
                d = abs(wy - target_y)
                candidates.append((wall_x, wy, d))
        else:
            # Primarily vertical — pick from north or south wall
            wall_y = rect.y2 - 1 if dy > 0 else rect.y
            for wx in range(rect.x + 1, rect.x2 - 1):
                d = abs(wx - target_x)
                candidates.append((wx, wall_y, d))

        if not candidates:
            # Fallback: any non-corner border tile
            for wy in range(rect.y + 1, rect.y2 - 1):
                candidates.append((rect.x, wy, 0))
                candidates.append((rect.x2 - 1, wy, 0))
            for wx in range(rect.x + 1, rect.x2 - 1):
                candidates.append((wx, rect.y, 0))
                candidates.append((wx, rect.y2 - 1, 0))

        if not candidates:
            return cx, cy

        candidates.sort(key=lambda c: c[2])
        return candidates[0][0], candidates[0][1]

    def _connect(
        self, level: Level, a: Rect, b: Rect, rng: random.Random,
    ) -> None:
        """Connect two rooms with an L-shaped corridor.

        Entry points are on room borders (not corners). The corridor
        is carved one tile OUTSIDE each room wall, through void.
        """
        bx, by = b.center
        ax, ay = a.center

        # Find entry points on each room's wall
        ex_a_x, ex_a_y = self._find_entry_point(level, a, bx, by)
        ex_b_x, ex_b_y = self._find_entry_point(level, b, ax, ay)

        # Step one tile outside each room wall to start the corridor
        def _step_outside(room: Rect, wx: int, wy: int) -> tuple[int, int]:
            if wx == room.x:
                return wx - 1, wy
            if wx == room.x2 - 1:
                return wx + 1, wy
            if wy == room.y:
                return wx, wy - 1
            if wy == room.y2 - 1:
                return wx, wy + 1
            return wx, wy

        start_x, start_y = _step_outside(a, ex_a_x, ex_a_y)
        end_x, end_y = _step_outside(b, ex_b_x, ex_b_y)

        # Carve L-shaped corridor between start and end
        if rng.random() < 0.5:
            self._carve_h(level, start_x, end_x, start_y)
            self._carve_v(level, start_y, end_y, end_x)
        else:
            self._carve_v(level, start_y, end_y, start_x)
            self._carve_h(level, start_x, end_x, end_y)

    def _carve_h(self, level: Level, x1: int, x2: int, y: int) -> None:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if level.in_bounds(x, y):
                t = level.tiles[y][x]
                if t.terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                              is_corridor=True)

    def _carve_v(self, level: Level, y1: int, y2: int, x: int) -> None:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if level.in_bounds(x, y):
                t = level.tiles[y][x]
                if t.terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                              is_corridor=True)

    def _set_door(
        self, level: Level, x: int, y: int,
        rng: random.Random, secret_chance: float,
        door_positions: set[tuple[int, int]],
    ) -> None:
        """Convert a tile to a door, or just open it if a door is nearby."""
        if (x, y) in door_positions:
            return
        too_close = any(
            (x + ddx, y + ddy) in door_positions
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        )
        if too_close:
            # Door nearby — just make passable (no double door)
            if level.tiles[y][x].terrain == Terrain.WALL:
                level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
        else:
            feat = ("door_secret" if rng.random() < secret_chance
                    else "door_closed")
            level.tiles[y][x] = Tile(terrain=Terrain.FLOOR, feature=feat)
            door_positions.add((x, y))

    def _place_junction_doors(
        self, level: Level, rng: random.Random, secret_chance: float,
    ) -> None:
        """Place a door wherever a corridor tile is adjacent to a room wall.

        The wall tile between the corridor and the room floor becomes
        a door (closed or secret).
        """
        door_positions: set[tuple[int, int]] = set()

        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if tile.terrain != Terrain.WALL:
                    continue
                # Is this wall between a corridor and a room floor?
                has_corridor = False
                has_room = False
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nb = level.tile_at(x + dx, y + dy)
                    if nb and nb.terrain == Terrain.FLOOR:
                        if nb.is_corridor:
                            has_corridor = True
                        else:
                            has_room = True
                if has_corridor and has_room:
                    # Skip if too close to another door
                    too_close = any(
                        (x + dx, y + dy) in door_positions
                        for dx in range(-2, 3) for dy in range(-2, 3)
                        if (dx, dy) != (0, 0)
                    )
                    if too_close:
                        continue

                    # Convert wall to door
                    if rng.random() < secret_chance:
                        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                                  feature="door_secret")
                    else:
                        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                                  feature="door_closed")
                    door_positions.add((x, y))

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

        # ── Step 1: Carve rooms ──
        for rect in rects:
            self._carve_room(level, rect)
        for i, rect in enumerate(rects):
            level.rooms.append(Room(id=f"room_{i + 1}", rect=rect))
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
                self._carve_corridor(level, rects[a], rects[b], rng)
        else:
            logger.warning("No main path found between entrance and exit")

        # Extra loops
        extra = 0
        for i, j in neighbors:
            pair = (min(i, j), max(i, j))
            if pair not in connected and rng.random() < params.connectivity * 0.5:
                connected.add(pair)
                self._carve_corridor(level, rects[i], rects[j], rng)
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
                        level, rects[idx], rects[best_other], rng,
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

        # ── Step 4: Stairs ──
        sx, sy = rects[entrance].center
        level.tiles[sy][sx].feature = "stairs_up"
        ex, ey = rects[exit_idx].center
        level.tiles[ey][ex].feature = "stairs_down"
        level.rooms[entrance].tags.append("entry")
        level.rooms[exit_idx].tags.append("exit")

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

    def _wall_entry(
        self, level: Level, rect: Rect, tx: int, ty: int,
    ) -> tuple[int, int]:
        """Find a non-corner wall tile on *rect* facing (tx, ty).

        Scans the wall tiles (built by _build_walls) one tile outside
        the room rect on the side closest to the target.  Returns the
        wall position.
        """
        cx, cy = rect.center
        dx, dy = tx - cx, ty - cy

        def _has_adjacent_door(wx: int, wy: int) -> bool:
            for ddx, ddy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = level.tile_at(wx + ddx, wy + ddy)
                if nb and nb.feature in (
                    "door_closed", "door_open", "door_secret",
                ):
                    return True
            return False

        def _near_corner(wx: int, wy: int) -> bool:
            """True if this wall position is at or adjacent to a corner."""
            corners = [
                (rect.x - 1, rect.y - 1), (rect.x2, rect.y - 1),
                (rect.x - 1, rect.y2), (rect.x2, rect.y2),
            ]
            for cx, cy in corners:
                if abs(wx - cx) + abs(wy - cy) <= 1:
                    return True
            return False

        # Collect candidate wall tiles on the facing side
        # Skip corners and tiles adjacent to existing doors
        cands: list[tuple[int, int, int]] = []
        if abs(dx) >= abs(dy):
            # East or west wall (skip first/last = corners)
            wx = rect.x2 if dx > 0 else rect.x - 1
            for wy in range(rect.y, rect.y2):
                if _near_corner(wx, wy):
                    continue
                t = level.tile_at(wx, wy)
                if (t and t.terrain == Terrain.WALL
                        and not _has_adjacent_door(wx, wy)):
                    cands.append((wx, wy, abs(wy - ty)))
        else:
            # North or south wall (skip first/last = corners)
            wy = rect.y2 if dy > 0 else rect.y - 1
            for wx in range(rect.x, rect.x2):
                if _near_corner(wx, wy):
                    continue
                t = level.tile_at(wx, wy)
                if (t and t.terrain == Terrain.WALL
                        and not _has_adjacent_door(wx, wy)):
                    cands.append((wx, wy, abs(wx - tx)))

        # Fallback: any non-corner wall around the room
        if not cands:
            for side_x in (rect.x - 1, rect.x2):
                for wy in range(rect.y, rect.y2):
                    if _near_corner(side_x, wy):
                        continue
                    t = level.tile_at(side_x, wy)
                    if (t and t.terrain == Terrain.WALL
                            and not _has_adjacent_door(side_x, wy)):
                        cands.append((side_x, wy, 0))
            for side_y in (rect.y - 1, rect.y2):
                for wx in range(rect.x, rect.x2):
                    if _near_corner(wx, side_y):
                        continue
                    t = level.tile_at(wx, side_y)
                    if (t and t.terrain == Terrain.WALL
                            and not _has_adjacent_door(wx, side_y)):
                        cands.append((wx, side_y, 0))

        if not cands:
            return cx, cy
        cands.sort(key=lambda c: c[2])
        return cands[0][0], cands[0][1]

    def _carve_corridor(
        self, level: Level, a: Rect, b: Rect, rng: random.Random,
    ) -> None:
        """Connect two rooms by carving through VOID only.

        1. Find wall entry on each room facing the other.
        2. Convert each wall entry to a door.
        3. Step one tile outside into VOID.
        4. Carve an L-shaped path through VOID between those points.
        """
        bx, by = b.center
        ax, ay = a.center

        # Wall entries
        wa_x, wa_y = self._wall_entry(level, a, bx, by)
        wb_x, wb_y = self._wall_entry(level, b, ax, ay)

        # Convert wall entries to doors
        secret = rng.random() < 0.1
        for wx, wy in [(wa_x, wa_y), (wb_x, wb_y)]:
            t = level.tile_at(wx, wy)
            if t and t.terrain == Terrain.WALL:
                feat = "door_secret" if secret else "door_closed"
                level.tiles[wy][wx] = Tile(
                    terrain=Terrain.FLOOR, feature=feat,
                )

        # Step one tile outside each door into VOID
        def _outward(room: Rect, wx: int, wy: int) -> tuple[int, int]:
            if wx < room.x:
                return wx - 1, wy
            if wx >= room.x2:
                return wx + 1, wy
            if wy < room.y:
                return wx, wy - 1
            if wy >= room.y2:
                return wx, wy + 1
            return wx, wy  # shouldn't happen

        sx, sy = _outward(a, wa_x, wa_y)
        ex, ey = _outward(b, wb_x, wb_y)

        # Carve L-shaped corridor through VOID only
        if rng.random() < 0.5:
            self._carve_line(level, sx, sy, ex, sy)   # horizontal
            self._carve_line(level, ex, sy, ex, ey)   # vertical
        else:
            self._carve_line(level, sx, sy, sx, ey)   # vertical
            self._carve_line(level, sx, ey, ex, ey)   # horizontal

    def _carve_line(
        self, level: Level, x1: int, y1: int, x2: int, y2: int,
    ) -> None:
        """Carve a straight corridor line.  Only replaces VOID tiles."""
        if y1 == y2:
            for x in range(min(x1, x2), max(x1, x2) + 1):
                if level.in_bounds(x, y1):
                    t = level.tiles[y1][x]
                    if t.terrain == Terrain.VOID:
                        level.tiles[y1][x] = Tile(
                            terrain=Terrain.FLOOR, is_corridor=True,
                        )
        else:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                if level.in_bounds(x1, y):
                    t = level.tiles[y][x1]
                    if t.terrain == Terrain.VOID:
                        level.tiles[y][x1] = Tile(
                            terrain=Terrain.FLOOR, is_corridor=True,
                        )

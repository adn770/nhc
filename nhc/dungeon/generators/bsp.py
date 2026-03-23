"""BSP (Binary Space Partitioning) dungeon generator.

Recursively subdivides the map into regions, places rooms within each
leaf, then connects them via corridors with main path + extra loops.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

from nhc.dungeon.generator import DungeonGenerator, GenerationParams
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

MIN_LEAF = 8
MAX_ROOM = 10
MIN_ROOM = 4
PADDING = 1


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

def _find_neighbors(rects: list[Rect], gap: int = 5) -> list[tuple[int, int]]:
    """Find room pairs close enough to connect."""
    pairs: list[tuple[int, int]] = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            h_overlap = min(a.x2, b.x2) - max(a.x, b.x)
            v_overlap = min(a.y2, b.y2) - max(a.y, b.y)
            h_gap = max(a.x, b.x) - min(a.x2, b.x2)
            v_gap = max(a.y, b.y) - min(a.y2, b.y2)
            if h_overlap >= 2 and 0 <= v_gap <= gap:
                pairs.append((i, j))
            elif v_overlap >= 2 and 0 <= h_gap <= gap:
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
        for leaf in root.leaves():
            _place_room(leaf, rng)

        rects = [lf.room for lf in root.leaves() if lf.room]
        if len(rects) < 3:
            from nhc.dungeon.classic import ClassicGenerator
            return ClassicGenerator().generate(params)

        # Carve rooms
        for rect in rects:
            self._carve_room(level, rect)
        for i, rect in enumerate(rects):
            level.rooms.append(Room(id=f"room_{i + 1}", rect=rect))

        # ── 2. Connectivity ──
        neighbors = _find_neighbors(rects)
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for i, j in neighbors:
            adj[i].add(j)
            adj[j].add(i)

        # Pick entrance/exit (maximize distance)
        entrance = 0
        dists = _bfs_dist(adj, entrance)
        exit_idx = max(dists, key=dists.get) if dists else len(rects) - 1

        # Main path
        connected: set[tuple[int, int]] = set()
        main_path = _bfs(adj, entrance, exit_idx)
        if main_path:
            for k in range(len(main_path) - 1):
                a, b = main_path[k], main_path[k + 1]
                pair = (min(a, b), max(a, b))
                connected.add(pair)
                self._connect(level, rects[a], rects[b], rng)

        # Extra loops
        for i, j in neighbors:
            pair = (min(i, j), max(i, j))
            if pair not in connected and rng.random() < params.connectivity * 0.5:
                connected.add(pair)
                self._connect(level, rects[i], rects[j], rng)

        # Ensure full reachability
        for idx in range(len(rects)):
            if _bfs(adj, entrance, idx) is None:
                # Connect to any neighbor
                for ni, nj in neighbors:
                    other = nj if ni == idx else (ni if nj == idx else None)
                    if other is not None:
                        pair = (min(idx, other), max(idx, other))
                        if pair not in connected:
                            connected.add(pair)
                            self._connect(level, rects[idx], rects[other], rng)
                            break

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

        # ── 4. Doors ──
        self._place_doors(level, rng, params.secret_doors)

        return level

    # ── Carving helpers ─────────────────────────────────────────────

    def _carve_room(self, level: Level, rect: Rect) -> None:
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                if level.in_bounds(x, y):
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)

    def _connect(
        self, level: Level, a: Rect, b: Rect, rng: random.Random,
    ) -> None:
        ax, ay = a.center
        bx, by = b.center
        if rng.random() < 0.5:
            self._h(level, ax, bx, ay)
            self._v(level, ay, by, bx)
        else:
            self._v(level, ay, by, ax)
            self._h(level, ax, bx, by)

    def _h(self, level: Level, x1: int, x2: int, y: int) -> None:
        for x in range(min(x1, x2), max(x1, x2) + 1):
            if level.in_bounds(x, y):
                if level.tiles[y][x].terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                              is_corridor=True)

    def _v(self, level: Level, y1: int, y2: int, x: int) -> None:
        for y in range(min(y1, y2), max(y1, y2) + 1):
            if level.in_bounds(x, y):
                if level.tiles[y][x].terrain != Terrain.FLOOR:
                    level.tiles[y][x] = Tile(terrain=Terrain.FLOOR,
                                              is_corridor=True)

    def _place_doors(
        self, level: Level, rng: random.Random, secret_chance: float,
    ) -> None:
        for y in range(1, level.height - 1):
            for x in range(1, level.width - 1):
                tile = level.tiles[y][x]
                if tile.terrain != Terrain.FLOOR or tile.feature:
                    continue
                h_walls = (
                    level.tiles[y - 1][x].terrain == Terrain.WALL
                    and level.tiles[y + 1][x].terrain == Terrain.WALL
                )
                v_walls = (
                    level.tiles[y][x - 1].terrain == Terrain.WALL
                    and level.tiles[y][x + 1].terrain == Terrain.WALL
                )
                if not (h_walls or v_walls):
                    continue
                adj_floor = sum(
                    1 for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                    if (level.in_bounds(x + dx, y + dy)
                        and level.tiles[y + dy][x + dx].terrain
                        == Terrain.FLOOR)
                )
                if adj_floor == 2:
                    if rng.random() < secret_chance:
                        tile.feature = "door_secret"
                    else:
                        tile.feature = "door_closed"

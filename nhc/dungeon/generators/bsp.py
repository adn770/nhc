"""BSP (Binary Space Partitioning) dungeon generator.

Recursively subdivides the map into regions, places rooms within each
leaf, then connects them via corridors with main path + extra loops.
"""

from __future__ import annotations

import logging
import random
from typing import Callable

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
    PillShape,
    Rect,
    RectShape,
    Room,
    RoomShape,
    TempleShape,
    Terrain,
    Tile,
)
from nhc.utils.rng import get_rng

from nhc.dungeon.generators._bsp_tree import (
    MAX_ROOM,
    MIN_ROOM,
    PADDING,
    _Node,
    _place_room,
    _split,
)
from nhc.dungeon.generators._connectivity import (
    _bfs,
    _bfs_dist,
    _center_dist,
    _find_neighbors,
)
from nhc.dungeon.generators._doors import (
    _compute_door_sides,
    _door_candidates,
    _remove_non_straight_doors,
)

MIN_LEAF = 9  # kept for backward compat; canonical copy in _bsp_tree


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

        # Depth 2 must always offer a temple sanctuary.  Ensure at
        # least one rect satisfies TempleShape's geometric needs:
        # min_dim >= 7 AND both dims odd (clean cap geometry, no
        # walled-tunnel adjacency).  Resize a leaf's room rect in
        # place so corridor planning sees the final rect.
        # See nhc.dungeon.room_types.TEMPLE_MIN_DEPTH.
        def _temple_ready(r: Rect) -> bool:
            return (min(r.width, r.height) >= 7
                    and r.width % 2 == 1 and r.height % 2 == 1)

        if params.depth == 2 and not any(_temple_ready(r) for r in rects):
            best_leaf = None
            best_slack = -1
            for lf in leaves:
                if lf.room is None:
                    continue
                avail_w = lf.rect.width - PADDING * 2
                avail_h = lf.rect.height - PADDING * 2
                slack = min(avail_w, avail_h)
                if slack > best_slack:
                    best_slack = slack
                    best_leaf = lf
            if best_leaf is not None and best_slack >= 7:
                avail_w = best_leaf.rect.width - PADDING * 2
                avail_h = best_leaf.rect.height - PADDING * 2
                new_w = min(MAX_ROOM, max(7, avail_w))
                new_h = min(MAX_ROOM, max(7, avail_h))
                if new_w % 2 == 0:
                    new_w -= 1
                if new_h % 2 == 0:
                    new_h -= 1
                nx = best_leaf.rect.x + PADDING
                ny = best_leaf.rect.y + PADDING
                # Update both the leaf's room and our local rects list.
                old = best_leaf.room
                best_leaf.room = Rect(nx, ny, new_w, new_h)
                for i, r in enumerate(rects):
                    if r is old:
                        rects[i] = best_leaf.room
                        break

        # ── Step 1: Carve rooms ──
        shapes = [
            self._pick_shape(rect, params.shape_variety, rng)
            for rect in rects
        ]
        # Depth 2 must always offer a temple sanctuary — force one
        # eligible room into TempleShape if none was naturally picked.
        # Both dims must be odd so TempleShape's caps align with the
        # rect bounds and don't create walled-tunnel adjacency.
        if params.depth == 2 and not any(
            isinstance(s, TempleShape) for s in shapes
        ):
            ranked = sorted(
                range(len(rects)),
                key=lambda i: -min(rects[i].width, rects[i].height),
            )
            for i in ranked:
                r = rects[i]
                if (min(r.width, r.height) >= 7
                        and r.width % 2 == 1
                        and r.height % 2 == 1):
                    shapes[i] = TempleShape(
                        flat_side=rng.choice(TempleShape.VALID_SIDES),
                    )
                    break
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

        # ── Step 3e: Strip walled-tunnel adjacency ──
        # If a corridor tile has WALLs on both perpendicular sides,
        # demote one of those walls to VOID — corridors must show as
        # open passages, not as 1-tile walled tunnels (this can occur
        # when a TempleShape clipped corner sits next to a corridor).
        self._fix_walled_corridors(level)

        # ── Step 3f: Vault rooms ──
        # Tiny 2x2 / 3x2 treasure rooms hidden in void space with
        # no corridor connection.  Placed *after* all connectivity
        # work so the flood-fill reconnection (Step 3d) cannot
        # accidentally link them back into the main dungeon.
        self._place_vaults(level, rng, params)

        # ── Step 4: Stairs ──
        self._place_stairs(level, rects, adj, rng)

        # Compute door_side for all door tiles
        _compute_door_sides(level)

        # Remove doors on non-straight wall sections (arcs, diagonals)
        _remove_non_straight_doors(level)

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


    # ── Carving helpers ─────────────────────────────────────────────

    def _fix_walled_corridors(self, level: Level) -> None:
        """Remove walls causing walled-tunnel adjacency on corridors.

        For each corridor tile, if both perpendicular neighbours are
        WALL (and neither is bordering an actual room floor on its
        opposite side), demote the wall whose removal does not orphan
        a room cell.  Targeted at TempleShape clipped corners that
        place WALLs in cells the corridor would prefer to have as VOID.
        """
        from nhc.dungeon.model import Terrain, Tile

        def _is_room_neighbor(x: int, y: int) -> bool:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                t = level.tile_at(x + dx, y + dy)
                if (t and t.terrain in (Terrain.FLOOR, Terrain.WATER)
                        and not t.is_corridor):
                    return True
            return False

        for y in range(level.height):
            for x in range(level.width):
                tile = level.tiles[y][x]
                if not (tile.terrain == Terrain.FLOOR
                        and tile.is_corridor):
                    continue
                pairs = (
                    ((x, y - 1), (x, y + 1)),  # N/S
                    ((x - 1, y), (x + 1, y)),  # E/W
                )
                for (ax, ay), (bx, by) in pairs:
                    a = level.tile_at(ax, ay)
                    b = level.tile_at(bx, by)
                    if not (a and b
                            and a.terrain == Terrain.WALL
                            and b.terrain == Terrain.WALL):
                        continue
                    # Demote the wall NOT serving a room cell — if
                    # both serve rooms, leave as-is (genuine choke).
                    a_room = _is_room_neighbor(ax, ay)
                    b_room = _is_room_neighbor(bx, by)
                    if a_room and not b_room:
                        level.tiles[by][bx] = Tile(terrain=Terrain.VOID)
                    elif b_room and not a_room:
                        level.tiles[ay][ax] = Tile(terrain=Terrain.VOID)
                    elif not a_room and not b_room:
                        # Neither serves a room — strip both.
                        level.tiles[ay][ax] = Tile(terrain=Terrain.VOID)
                        level.tiles[by][bx] = Tile(terrain=Terrain.VOID)

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

    def _place_vaults(
        self, level: Level, rng: random.Random,
        params: GenerationParams,
    ) -> list[Rect]:
        """Place 2x2 / 3x2 disconnected vault rooms in void space.

        Vaults are tiny treasure caches unreachable from the main
        dungeon.  Players can only get in by digging through a
        wall.  Each vault is added to ``level.rooms`` with a
        ``"vault"`` tag but is never inserted into the BSP
        adjacency graph, so corridor carving and flood-fill
        reconnection leave it untouched.
        """
        target = 1 + params.depth // 2 + rng.randint(0, 1)
        sizes = [(2, 2), (3, 2), (2, 3)]
        placed: list[Rect] = []
        attempts = 0
        max_attempts = 300
        # Buffer in tiles around the vault: the inner ring becomes
        # the vault's own wall, the outer ring stays VOID so the
        # new walls never sit directly next to an existing corridor
        # or room wall (which would close the corridor into a
        # walled tunnel).
        BUFFER = 2

        while len(placed) < target and attempts < max_attempts:
            attempts += 1
            vw, vh = rng.choice(sizes)
            vx = rng.randint(
                BUFFER + 1, level.width - vw - BUFFER - 2,
            )
            vy = rng.randint(
                BUFFER + 1, level.height - vh - BUFFER - 2,
            )

            # The bounding box plus a BUFFER-tile border must be
            # entirely VOID — guarantees a clean wall ring and
            # prevents the new wall from sealing a neighbouring
            # corridor on both sides.
            box_ok = True
            for dy in range(-BUFFER, vh + BUFFER):
                if not box_ok:
                    break
                for dx in range(-BUFFER, vw + BUFFER):
                    t = level.tile_at(vx + dx, vy + dy)
                    if t is None or t.terrain != Terrain.VOID:
                        box_ok = False
                        break
            if not box_ok:
                continue

            # Carve the vault interior as plain FLOOR.
            for dy in range(vh):
                for dx in range(vw):
                    level.tiles[vy + dy][vx + dx] = Tile(
                        terrain=Terrain.FLOOR,
                    )
            # Wrap it in a solid wall ring (the border was VOID).
            for dy in range(-1, vh + 1):
                for dx in range(-1, vw + 1):
                    if 0 <= dx < vw and 0 <= dy < vh:
                        continue
                    level.tiles[vy + dy][vx + dx] = Tile(
                        terrain=Terrain.WALL,
                    )

            rect = Rect(vx, vy, vw, vh)
            placed.append(rect)
            level.rooms.append(Room(
                id=f"vault_{len(placed)}",
                rect=rect,
                shape=RectShape(),
                tags=["vault"],
            ))

        if placed:
            logger.info(
                "Placed %d vault(s) (target=%d, attempts=%d)",
                len(placed), target, attempts,
            )
        return placed

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

        # Collect eligible shape factories for this room size
        candidates: list[Callable[[], RoomShape]] = [
            OctagonShape, CrossShape,
        ]
        # Circles only for near-square rooms where both dimensions
        # are odd (ensures integer center and clean cardinal points)
        if (max_dim / min_dim <= 1.3
                and rect.width % 2 == 1 and rect.height % 2 == 1):
            candidates.append(CircleShape)
        # Pills only for elongated rooms where the short dimension
        # is odd (clean integer geometry for the semicircle caps).
        if (max_dim - min_dim >= 2 and min_dim >= 5 and min_dim % 2 == 1):
            candidates.append(PillShape)
        # Temples need room for 4 arms with rounded caps. Require
        # both dimensions odd and min_dim >= 7.
        if (min_dim >= 7
                and rect.width % 2 == 1 and rect.height % 2 == 1):
            candidates.append(
                lambda r=rng: TempleShape(
                    flat_side=r.choice(TempleShape.VALID_SIDES),
                )
            )

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

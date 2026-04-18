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
from nhc.dungeon.generators._corridors import (
    _carve_corridor,
    _carve_corridor_force,
)
from nhc.dungeon.generators._dead_ends import (
    _handle_dead_ends,
    _harmonize_doors,
    _prune_dead_ends,
    _remove_orphaned_doors,
    _verify_connectivity,
)
from nhc.dungeon.generators._stairs import _place_stairs
from nhc.dungeon.generators._vaults import _place_vaults
from nhc.dungeon.generators._walls import _build_walls, _fix_walled_corridors
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
        _build_walls(level)

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
                _carve_corridor(
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
                _carve_corridor(
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
                    _carve_corridor(
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
        _prune_dead_ends(level)

        # ── Step 3b: Handle dead-end corridor stubs ──
        _handle_dead_ends(level, rng)

        # ── Step 3c: Remove orphaned doors ──
        _remove_orphaned_doors(level)

        # ── Step 3d: Verify connectivity via flood fill ──
        _verify_connectivity(level, rects, entrance, rng)

        # ── Step 3e: Final door harmonization ──
        _harmonize_doors(level)

        # ── Step 3e: Strip walled-tunnel adjacency ──
        # If a corridor tile has WALLs on both perpendicular sides,
        # demote one of those walls to VOID — corridors must show as
        # open passages, not as 1-tile walled tunnels (this can occur
        # when a TempleShape clipped corner sits next to a corridor).
        _fix_walled_corridors(level)

        # ── Step 3f: Vault rooms ──
        # Tiny 2x2 / 3x2 treasure rooms hidden in void space with
        # no corridor connection.  Placed *after* all connectivity
        # work so the flood-fill reconnection (Step 3d) cannot
        # accidentally link them back into the main dungeon.
        _place_vaults(level, rng, params)

        # ── Step 4: Stairs ──
        _place_stairs(level, rects, adj, rng)

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


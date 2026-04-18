"""BSP (Binary Space Partitioning) dungeon generator.

Recursively subdivides the map into regions, places rooms within each
leaf, then connects them via corridors with main path + extra loops.
"""

from __future__ import annotations

import logging
import random

from nhc.dungeon.generator import DungeonGenerator, GenerationParams
from nhc.dungeon.model import (
    Corridor,
    Level,
    LevelMetadata,
    Rect,
    Room,
    TempleShape,
    Terrain,
)
from nhc.utils.rng import get_rng

logger = logging.getLogger(__name__)

from nhc.dungeon.generators._bsp_tree import (
    MAX_ROOM,
    MIN_ROOM,
    PADDING,
    _Node,
    _place_room,
    _split,
)
from nhc.dungeon.generators._corridors import _carve_corridor
from nhc.dungeon.generators._layout import LAYOUT_STRATEGIES
from nhc.dungeon.generators._dead_ends import (
    _handle_dead_ends,
    _harmonize_doors,
    _prune_dead_ends,
    _remove_orphaned_doors,
    _verify_connectivity,
)
from nhc.dungeon.generators._shapes import _carve_room, _pick_shape
from nhc.dungeon.generators._stairs import _place_stairs
from nhc.dungeon.generators._vaults import _place_vaults
from nhc.dungeon.generators._walls import _build_walls, _fix_walled_corridors
from nhc.dungeon.generators._doors import (
    _compute_door_sides,
    _door_candidates,
    _remove_non_straight_doors,
)


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
            template=params.template,
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
            _pick_shape(rect, params.shape_variety, rng,
                        preferred_shapes=params.preferred_shapes)
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
            _carve_room(level, rect, shape)
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

        # ── Step 3: Connectivity — carve corridors ──
        strategy = LAYOUT_STRATEGIES.get(
            params.layout_strategy, LAYOUT_STRATEGIES["default"],
        )
        pairs, entrance, exit_idx = strategy(
            rects, params.connectivity, rng,
        )
        logger.info(
            "Layout '%s': %d pairs, entrance=room_%d, exit=room_%d",
            params.layout_strategy, len(pairs), entrance + 1,
            exit_idx + 1,
        )

        connected: set[tuple[int, int]] = set()
        for a, b in pairs:
            pair = (min(a, b), max(a, b))
            if pair not in connected:
                connected.add(pair)
                _carve_corridor(
                    level, level.rooms[a], level.rooms[b], rng,
                )

        # Build adj from connected pairs for downstream use
        adj: dict[int, set[int]] = {i: set() for i in range(len(rects))}
        for a, b in connected:
            adj[a].add(b)
            adj[b].add(a)

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



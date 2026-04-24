"""Rect BSP partitioner — doorway mode.

See ``design/building_interiors.md``. Recursively splits a rect
footprint into leaves separated by 1-tile interior walls; each
leaf becomes a Room and each internal split gets one door on its
wall. "Doorway mode" places doors directly between neighbouring
rooms with no corridor.

Corridor mode (M9) shares the same tree but replaces the root
split wall with a 1-or-2-tile wide corridor; corridor-mode rooms
access the corridor through doorways.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import (
    LShape, Rect, RectShape, Room, canonicalize,
)


@dataclass
class _Split:
    axis: str                           # "horiz" | "vert"
    at: int                             # absolute coord of wall line
    wall: set[tuple[int, int]] = field(default_factory=set)


@dataclass
class _BSPNode:
    rect: Rect
    split: _Split | None = None
    left: "_BSPNode | None" = None
    right: "_BSPNode | None" = None

    @property
    def is_leaf(self) -> bool:
        return self.split is None


class RectBSPPartitioner:
    """BSP split + doorway-style doors on each split's wall."""

    def __init__(self, mode: str = "doorway") -> None:
        if mode not in ("doorway", "corridor"):
            raise ValueError(
                f"RectBSPPartitioner mode must be 'doorway' or "
                f"'corridor'; got {mode!r}"
            )
        self.mode = mode

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} outside shape"
            )
        if isinstance(cfg.shape, LShape):
            return self._plan_lshape(cfg)
        if self.mode == "corridor":
            return self._plan_corridor(cfg)
        return self._plan_doorway(cfg)

    def _plan_lshape(self, cfg: PartitionerConfig) -> LayoutPlan:
        """Partition an L-shape as two arms, then BSP each arm.

        Rect-BSP naïvely splits the bounding rect, so an L-shape
        used to leak leaves and doors into the notch; after the
        shell stamps walls those doors became stranded FLOOR
        tiles and whole rooms (including the stairs) were
        unreachable. Splitting at the L's inner corner first
        guarantees every leaf and door stays inside the footprint.
        """
        shape = cfg.shape
        assert isinstance(shape, LShape)
        rect = cfg.footprint
        notch = shape._notch_rect(rect)
        arms = self._lshape_arms(rect, notch, shape.corner)
        if arms is None:
            return SingleRoomPartitioner().plan(cfg)
        arm_a, arm_b, edge_xs, edge_y = arms
        min_room = cfg.min_room
        if (
            arm_a.width < min_room or arm_a.height < min_room
            or arm_b.width < min_room or arm_b.height < min_room
        ):
            return SingleRoomPartitioner().plan(cfg)

        junction_door = self._pick_junction_door(
            edge_xs, edge_y, cfg.rng, cfg.required_walkable,
        )
        if junction_door is None:
            return SingleRoomPartitioner().plan(cfg)

        target = cfg.rng.randint(3, 5)
        area_a = arm_a.width * arm_a.height
        area_b = arm_b.width * arm_b.height
        target_a = max(1, round(target * area_a / (area_a + area_b)))
        target_b = max(1, target - target_a)

        req_a = frozenset(
            t for t in cfg.required_walkable
            if (arm_a.x <= t[0] < arm_a.x2
                and arm_a.y <= t[1] < arm_a.y2)
        )
        req_b = frozenset(
            t for t in cfg.required_walkable
            if (arm_b.x <= t[0] < arm_b.x2
                and arm_b.y <= t[1] < arm_b.y2)
        )

        tree_a = self._build_tree_to_target(
            arm_a, min_room, cfg.rng, req_a, target_a,
        )
        tree_b = self._build_tree_to_target(
            arm_b, min_room, cfg.rng, req_b, target_b,
        )
        leaves = (
            self._leaves_grown(tree_a) + self._leaves_grown(tree_b)
        )

        edges = (
            self._collect_edges(tree_a)
            | self._collect_edges(tree_b)
            | {canonicalize(x, edge_y, "north") for x in edge_xs}
        )
        doors = (
            self._place_edge_doors(tree_a, cfg)
            + self._place_edge_doors(tree_b, cfg)
            + [junction_door]
        )

        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_r{i}",
                rect=leaf,
                shape=RectShape(),
                tags=[],
            )
            for i, leaf in enumerate(leaves)
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_edges=edges,
            doors=doors,
        )

    def _lshape_arms(
        self, rect: Rect, notch: Rect, corner: str,
    ) -> tuple[Rect, Rect, range, int] | None:
        """Return ``(arm_a, arm_b, edge_xs, edge_y)`` for the L.

        Mirrors :class:`LShapePartitioner`'s geometry; the junction
        edge is always horizontal — ``(x, edge_y, "north")`` for
        ``x in edge_xs``.
        """
        if corner == "nw":
            arm_a = Rect(
                notch.x2, rect.y,
                rect.x2 - notch.x2, notch.height,
            )
            arm_b = Rect(
                rect.x, notch.y2,
                rect.width, rect.y2 - notch.y2,
            )
            return arm_a, arm_b, range(notch.x2, rect.x2), notch.y2
        if corner == "ne":
            arm_a = Rect(
                rect.x, rect.y,
                notch.x - rect.x, notch.height,
            )
            arm_b = Rect(
                rect.x, notch.y2,
                rect.width, rect.y2 - notch.y2,
            )
            return arm_a, arm_b, range(rect.x, notch.x), notch.y2
        if corner == "sw":
            arm_a = Rect(
                rect.x, rect.y,
                rect.width, notch.y - rect.y,
            )
            arm_b = Rect(
                notch.x2, notch.y,
                rect.x2 - notch.x2, notch.height,
            )
            return arm_a, arm_b, range(notch.x2, rect.x2), notch.y
        if corner == "se":
            arm_a = Rect(
                rect.x, rect.y,
                rect.width, notch.y - rect.y,
            )
            arm_b = Rect(
                rect.x, notch.y,
                notch.x - rect.x, notch.height,
            )
            return arm_a, arm_b, range(rect.x, notch.x), notch.y
        return None

    def _pick_junction_door(
        self, edge_xs: range, edge_y: int,
        rng: random.Random,
        required: frozenset[tuple[int, int]],
    ) -> InteriorDoor | None:
        xs = list(edge_xs)
        if len(xs) < 3:
            return None
        interior = xs[1:-1]
        candidates = [
            (x, edge_y) for x in interior
            if (x, edge_y) not in required
        ]
        if not candidates:
            return None
        x, y = rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side="north", feature="door_closed",
        )

    def _plan_doorway(self, cfg: PartitionerConfig) -> LayoutPlan:
        target = cfg.rng.randint(3, 5)
        root = self._build_tree_to_target(
            cfg.footprint, cfg.min_room, cfg.rng,
            cfg.required_walkable, target,
        )
        leaves = self._leaves_grown(root)
        if not leaves:
            return SingleRoomPartitioner().plan(cfg)
        if len(leaves) == 1:
            return SingleRoomPartitioner().plan(cfg)

        edges = self._collect_edges(root)
        doors = self._place_edge_doors(root, cfg)

        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_r{i}",
                rect=leaf,
                shape=RectShape(),
                tags=[],
            )
            for i, leaf in enumerate(leaves)
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_edges=edges,
            doors=doors,
        )

    def _plan_corridor(self, cfg: PartitionerConfig) -> LayoutPlan:
        """Central corridor flanked by rooms.

        The longer axis determines corridor orientation: a wider
        footprint gets a horizontal corridor; a taller one gets a
        vertical corridor. Each half is then BSP-split in
        doorway-mode for its sub-rooms.
        """
        rect = cfg.footprint
        min_room = cfg.min_room
        cw = cfg.corridor_width
        axis = "horiz" if rect.width >= rect.height else "vert"

        # Perpendicular span must fit min_room + wall + corridor +
        # wall + min_room.
        perp_origin = rect.y if axis == "horiz" else rect.x
        perp_end = rect.y2 if axis == "horiz" else rect.x2
        lo = perp_origin + min_room
        hi = perp_end - min_room - cw - 2
        if lo > hi:
            return self._plan_doorway(cfg)

        positions = list(range(lo, hi + 1))
        cfg.rng.shuffle(positions)

        for top_wall_at in positions:
            plan = self._try_corridor_layout(
                cfg, axis, top_wall_at, cw,
            )
            if plan is not None:
                return plan
        return self._plan_doorway(cfg)

    def _try_corridor_layout(
        self, cfg: PartitionerConfig, axis: str,
        top_wall_at: int, cw: int,
    ) -> LayoutPlan | None:
        rect = cfg.footprint
        min_room = cfg.min_room
        bot_wall_at = top_wall_at + cw + 1

        _, corridor, _ = self._corridor_tiles(
            rect, axis, top_wall_at, cw,
        )

        # Grown rects absorb the former wall rows so every tile
        # outside the corridor lives in a leaf.
        if axis == "horiz":
            top_rect = Rect(
                rect.x, rect.y,
                rect.width, top_wall_at + 1 - rect.y,
            )
            bot_rect = Rect(
                rect.x, bot_wall_at,
                rect.width, rect.y2 - bot_wall_at,
            )
        else:
            top_rect = Rect(
                rect.x, rect.y,
                top_wall_at + 1 - rect.x, rect.height,
            )
            bot_rect = Rect(
                bot_wall_at, rect.y,
                rect.x2 - bot_wall_at, rect.height,
            )

        # Sub-split each half (doorway-style BSP, grown rects).
        total_target = cfg.rng.randint(3, 5)
        top_target = max(1, total_target // 2)
        bot_target = max(1, total_target - top_target)

        top_tree = self._build_tree_to_target(
            top_rect, min_room, cfg.rng,
            cfg.required_walkable, top_target,
        )
        bot_tree = self._build_tree_to_target(
            bot_rect, min_room, cfg.rng,
            cfg.required_walkable, bot_target,
        )
        top_leaves = self._leaves_grown(top_tree)
        bot_leaves = self._leaves_grown(bot_tree)

        sub_edges = (
            self._collect_edges(top_tree)
            | self._collect_edges(bot_tree)
        )
        sub_doors = self._place_edge_doors(top_tree, cfg) + (
            self._place_edge_doors(bot_tree, cfg)
        )

        corridor_edges = self._corridor_boundary_edges(
            rect, axis, top_wall_at, bot_wall_at,
        )

        corridor_doors: list[InteriorDoor] = []
        for leaf in top_leaves:
            d = self._pick_corridor_door(
                leaf, axis, top_wall_at, "top",
                cfg.rng, cfg.required_walkable,
            )
            if d is None:
                return None
            corridor_doors.append(d)
        for leaf in bot_leaves:
            d = self._pick_corridor_door(
                leaf, axis, bot_wall_at, "bottom",
                cfg.rng, cfg.required_walkable,
            )
            if d is None:
                return None
            corridor_doors.append(d)

        all_doors = sub_doors + corridor_doors
        edges = sub_edges | corridor_edges

        leaves = top_leaves + bot_leaves
        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_r{i}",
                rect=leaf,
                shape=RectShape(),
                tags=[],
            )
            for i, leaf in enumerate(leaves)
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_edges=edges,
            corridor_tiles=corridor,
            doors=all_doors,
        )

    def _corridor_boundary_edges(
        self, rect: Rect, axis: str,
        top_wall_at: int, bot_wall_at: int,
    ) -> set[tuple[int, int, str]]:
        """Canonical edges along the two corridor boundaries."""
        edges: set[tuple[int, int, str]] = set()
        if axis == "horiz":
            for x in range(rect.x, rect.x2):
                edges.add(canonicalize(x, top_wall_at + 1, "north"))
                edges.add(canonicalize(x, bot_wall_at, "north"))
        else:
            for y in range(rect.y, rect.y2):
                edges.add(canonicalize(top_wall_at + 1, y, "west"))
                edges.add(canonicalize(bot_wall_at, y, "west"))
        return edges

    def _corridor_tiles(
        self, rect: Rect, axis: str, top_wall_at: int, cw: int,
    ) -> tuple[
        set[tuple[int, int]],
        set[tuple[int, int]],
        set[tuple[int, int]],
    ]:
        bot_wall_at = top_wall_at + cw + 1
        if axis == "horiz":
            top_wall = {
                (x, top_wall_at) for x in range(rect.x, rect.x2)
            }
            bot_wall = {
                (x, bot_wall_at) for x in range(rect.x, rect.x2)
            }
            corridor = {
                (x, y)
                for y in range(top_wall_at + 1, bot_wall_at)
                for x in range(rect.x, rect.x2)
            }
        else:
            top_wall = {
                (top_wall_at, y) for y in range(rect.y, rect.y2)
            }
            bot_wall = {
                (bot_wall_at, y) for y in range(rect.y, rect.y2)
            }
            corridor = {
                (x, y)
                for x in range(top_wall_at + 1, bot_wall_at)
                for y in range(rect.y, rect.y2)
            }
        return top_wall, corridor, bot_wall

    def _pick_corridor_door(
        self, leaf: Rect, axis: str, wall_at: int, side: str,
        rng: random.Random,
        required: frozenset[tuple[int, int]],
    ) -> InteriorDoor | None:
        """Pick a door on the wall between ``leaf`` and the
        corridor. ``side`` is "top" when the leaf sits above the
        corridor (horiz) or left of it (vert); "bottom" for the
        mirrored case."""
        if axis == "horiz":
            # door x lies within leaf's width, not on leaf edge.
            lo = leaf.x + 1
            hi = leaf.x2 - 2
            if lo > hi:
                return None
            candidates = [
                (x, wall_at) for x in range(lo, hi + 1)
                if (x, wall_at) not in required
            ]
            door_side = "south" if side == "top" else "north"
        else:
            lo = leaf.y + 1
            hi = leaf.y2 - 2
            if lo > hi:
                return None
            candidates = [
                (wall_at, y) for y in range(lo, hi + 1)
                if (wall_at, y) not in required
            ]
            door_side = "east" if side == "top" else "west"
        if not candidates:
            return None
        x, y = rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side=door_side, feature="door_closed",
        )

    def _build_tree_to_target(
        self, rect: Rect, min_room: int, rng: random.Random,
        required: frozenset[tuple[int, int]], target: int,
    ) -> _BSPNode:
        """Greedy BSP: keep splitting the largest splittable leaf
        until we hit ``target`` leaves or no leaf can split."""
        root = _BSPNode(rect=rect)
        while self._leaf_count(root) < target:
            victim = self._pick_largest_splittable(root, min_room)
            if victim is None:
                break
            if not self._split_node(victim, min_room, rng, required):
                break
        return root

    def _leaf_count(self, node: _BSPNode) -> int:
        if node.is_leaf:
            return 1
        assert node.left is not None and node.right is not None
        return self._leaf_count(node.left) + self._leaf_count(node.right)

    def _pick_largest_splittable(
        self, node: _BSPNode, min_room: int,
    ) -> _BSPNode | None:
        leaves: list[_BSPNode] = []
        self._collect_leaves_nodes(node, leaves)
        splittable = [
            n for n in leaves
            if self._splittable_axes(n.rect, min_room)
        ]
        if not splittable:
            return None
        splittable.sort(
            key=lambda n: n.rect.width * n.rect.height,
            reverse=True,
        )
        return splittable[0]

    def _collect_leaves_nodes(
        self, node: _BSPNode, out: list[_BSPNode],
    ) -> None:
        if node.is_leaf:
            out.append(node)
            return
        assert node.left is not None and node.right is not None
        self._collect_leaves_nodes(node.left, out)
        self._collect_leaves_nodes(node.right, out)

    def _split_node(
        self, node: _BSPNode, min_room: int,
        rng: random.Random,
        required: frozenset[tuple[int, int]],
    ) -> bool:
        axes = self._splittable_axes(node.rect, min_room)
        rng.shuffle(axes)
        for axis in axes:
            split = self._pick_split(
                node.rect, axis, min_room, rng, required,
            )
            if split is not None:
                node.split = split
                left_rect, right_rect = self._child_rects(
                    node.rect, split,
                )
                node.left = _BSPNode(rect=left_rect)
                node.right = _BSPNode(rect=right_rect)
                return True
        return False

    def _splittable_axes(
        self, rect: Rect, min_room: int,
    ) -> list[str]:
        # Require strict room for both halves + a 1-tile wall.
        axes: list[str] = []
        if rect.height > 2 * min_room + 1:
            axes.append("horiz")
        if rect.width > 2 * min_room + 1:
            axes.append("vert")
        return axes

    def _pick_split(
        self, rect: Rect, axis: str, min_room: int,
        rng: random.Random, required: frozenset[tuple[int, int]],
    ) -> _Split | None:
        if axis == "horiz":
            lo = rect.y + min_room
            hi = rect.y2 - min_room - 1
        else:
            lo = rect.x + min_room
            hi = rect.x2 - min_room - 1
        if lo > hi:
            return None
        positions = list(range(lo, hi + 1))
        rng.shuffle(positions)
        for at in positions:
            wall = self._wall_line(rect, axis, at)
            if wall.isdisjoint(required):
                return _Split(axis=axis, at=at, wall=wall)
        return None

    def _wall_line(
        self, rect: Rect, axis: str, at: int,
    ) -> set[tuple[int, int]]:
        if axis == "horiz":
            return {(x, at) for x in range(rect.x, rect.x2)}
        return {(at, y) for y in range(rect.y, rect.y2)}

    def _child_rects(
        self, rect: Rect, split: _Split,
    ) -> tuple[Rect, Rect]:
        if split.axis == "horiz":
            left = Rect(
                rect.x, rect.y, rect.width, split.at - rect.y,
            )
            right = Rect(
                rect.x, split.at + 1,
                rect.width, rect.y2 - split.at - 1,
            )
        else:
            left = Rect(
                rect.x, rect.y, split.at - rect.x, rect.height,
            )
            right = Rect(
                split.at + 1, rect.y,
                rect.x2 - split.at - 1, rect.height,
            )
        return left, right

    def _leaves(self, node: _BSPNode) -> list[Rect]:
        if node.is_leaf:
            return [node.rect]
        assert node.left is not None and node.right is not None
        return self._leaves(node.left) + self._leaves(node.right)

    # ─── Edge-wall primitives ───────────────────────────────
    #
    # In the edge-wall model a split's "wall row" at coord ``at``
    # is absorbed into one of the two children so rooms fill the
    # footprint with no WALL tile rows. The canonical edge sits
    # between the grown leaf and the other leaf. ``_grow_rect``
    # expands a child rect by one tile toward the split line;
    # ``_collect_edges`` walks the tree and emits one canonical
    # edge-run per split; ``_place_edge_doors`` picks a door tile
    # on a grown leaf whose ``door_side`` targets the split edge.

    def _leaves_grown(self, node: _BSPNode) -> list[Rect]:
        """Return leaves grown to absorb their side of each split.

        Each split's wall row / column (tile at coord ``at``) is
        absorbed into the "top" (horiz) or "left" (vert) leaf in
        that split's subtree. Nested splits mean a single leaf may
        absorb on multiple axes, so we match each split against
        the leaf's ORIGINAL rect (``orig``) rather than its
        currently-grown rect.
        """
        originals = self._leaves(node)
        grown: list[list[int]] = [
            [r.x, r.y, r.width, r.height] for r in originals
        ]
        splits = self._collect_split_rects(node)
        for (axis, at, parent) in splits:
            if axis == "horiz":
                x0, x1 = parent.x, parent.x2
                for i, orig in enumerate(originals):
                    if orig.y2 != at:
                        continue
                    if orig.x < x0 or orig.x2 > x1:
                        continue
                    grown[i][3] += 1
            else:
                y0, y1 = parent.y, parent.y2
                for i, orig in enumerate(originals):
                    if orig.x2 != at:
                        continue
                    if orig.y < y0 or orig.y2 > y1:
                        continue
                    grown[i][2] += 1
        return [Rect(x, y, w, h) for (x, y, w, h) in grown]

    def _collect_split_rects(
        self, node: _BSPNode,
    ) -> list[tuple[str, int, Rect]]:
        """Return ``(axis, at, parent_rect)`` for every split."""
        out: list[tuple[str, int, Rect]] = []
        self._collect_split_rects_recursive(node, out)
        return out

    def _collect_split_rects_recursive(
        self, node: _BSPNode,
        out: list[tuple[str, int, Rect]],
    ) -> None:
        if node.split is None:
            return
        out.append((node.split.axis, node.split.at, node.rect))
        assert node.left is not None and node.right is not None
        self._collect_split_rects_recursive(node.left, out)
        self._collect_split_rects_recursive(node.right, out)

    def _collect_edges(
        self, node: _BSPNode,
    ) -> set[tuple[int, int, str]]:
        """Return canonical edges for every split in the tree."""
        edges: set[tuple[int, int, str]] = set()
        self._collect_edges_recursive(node, node.rect, edges)
        return edges

    def _collect_edges_recursive(
        self, node: _BSPNode, effective: Rect,
        edges: set[tuple[int, int, str]],
    ) -> None:
        """Emit edges for this node's split, then recurse.

        ``effective`` is the rect actually covered by this subtree
        in the final layout, i.e., ``node.rect`` widened by any
        column / row that an ancestor split absorbed into this
        side. Sub-split edges must span that full extent — otherwise
        the sub-split leaves a 1-tile opening on the absorbed
        column / row.
        """
        if node.split is None:
            return
        assert node.left is not None and node.right is not None
        at = node.split.at
        if node.split.axis == "horiz":
            # Edge between (x, at) and (x, at+1) for every x in the
            # effective span. Top child absorbs row ``at`` down to
            # y == at+1; bottom child keeps its rect.
            for x in range(effective.x, effective.x2):
                edges.add(canonicalize(x, at + 1, "north"))
            top_eff = Rect(
                effective.x, effective.y,
                effective.width, at + 1 - effective.y,
            )
            bot_eff = Rect(
                effective.x, at + 1,
                effective.width, effective.y2 - at - 1,
            )
        else:
            for y in range(effective.y, effective.y2):
                edges.add(canonicalize(at + 1, y, "west"))
            top_eff = Rect(
                effective.x, effective.y,
                at + 1 - effective.x, effective.height,
            )
            bot_eff = Rect(
                at + 1, effective.y,
                effective.x2 - at - 1, effective.height,
            )
        self._collect_edges_recursive(node.left, top_eff, edges)
        self._collect_edges_recursive(node.right, bot_eff, edges)

    def _place_edge_doors(
        self, node: _BSPNode, cfg: PartitionerConfig,
    ) -> list[InteriorDoor]:
        doors: list[InteriorDoor] = []
        self._place_edge_doors_recursive(node, cfg, doors)
        return doors

    def _place_edge_doors_recursive(
        self, node: _BSPNode, cfg: PartitionerConfig,
        doors: list[InteriorDoor],
    ) -> None:
        if node.split is None:
            return
        door = self._pick_edge_door(
            node.rect, node.split, cfg.rng, cfg.required_walkable,
        )
        if door is not None:
            doors.append(door)
        assert node.left is not None and node.right is not None
        self._place_edge_doors_recursive(node.left, cfg, doors)
        self._place_edge_doors_recursive(node.right, cfg, doors)

    def _pick_edge_door(
        self, rect: Rect, split: _Split, rng: random.Random,
        required: frozenset[tuple[int, int]],
    ) -> InteriorDoor | None:
        """Pick a door tile on the grown-leaf side of the split.

        Interior candidates: exclude the two end tiles of the
        split line so the door sits on a run of ≥ 3 edges.
        Horizontal split at ``at`` → door tile (x, at+1) with
        door_side="north"; vertical split at ``at`` → door tile
        (at+1, y) with door_side="west". Either form's canonical
        edge matches one of the edges emitted by the split.
        """
        if split.axis == "horiz":
            lo = rect.x + 1
            hi = rect.x2 - 2
            if lo > hi:
                return None
            candidates = [
                (x, split.at + 1) for x in range(lo, hi + 1)
                if (x, split.at + 1) not in required
            ]
            side = "north"
        else:
            lo = rect.y + 1
            hi = rect.y2 - 2
            if lo > hi:
                return None
            candidates = [
                (split.at + 1, y) for y in range(lo, hi + 1)
                if (split.at + 1, y) not in required
            ]
            side = "west"
        if not candidates:
            return None
        x, y = rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side=side, feature="door_closed",
        )

    def _collect_walls(
        self, node: _BSPNode,
    ) -> set[tuple[int, int]]:
        walls: set[tuple[int, int]] = set()
        if node.split is not None:
            walls |= node.split.wall
        if node.left is not None:
            walls |= self._collect_walls(node.left)
        if node.right is not None:
            walls |= self._collect_walls(node.right)
        return walls

    def _place_doors(
        self, node: _BSPNode, cfg: PartitionerConfig,
    ) -> list[InteriorDoor]:
        doors: list[InteriorDoor] = []
        self._place_doors_recursive(node, cfg, doors)
        return doors

    def _place_doors_recursive(
        self, node: _BSPNode, cfg: PartitionerConfig,
        doors: list[InteriorDoor],
    ) -> None:
        if node.split is None:
            return
        door = self._pick_door_for_split(
            node.rect, node.split, cfg.rng, cfg.required_walkable,
        )
        if door is not None:
            doors.append(door)
        assert node.left is not None and node.right is not None
        self._place_doors_recursive(node.left, cfg, doors)
        self._place_doors_recursive(node.right, cfg, doors)

    def _pick_door_for_split(
        self, rect: Rect, split: _Split, rng: random.Random,
        required: frozenset[tuple[int, int]],
    ) -> InteriorDoor | None:
        """Pick a wall tile that has at least one wall tile on both
        axis-aligned sides (i.e., run length ≥ 3 at the door), and
        that does not overlap ``required``."""
        # Interior candidates: exclude first and last tile so door
        # sits on a run of ≥ 3 wall tiles.
        if split.axis == "horiz":
            lo = rect.x + 1
            hi = rect.x2 - 2
            if lo > hi:
                return None
            candidates = [
                (x, split.at) for x in range(lo, hi + 1)
                if (x, split.at) not in required
            ]
            side = "north"
        else:
            lo = rect.y + 1
            hi = rect.y2 - 2
            if lo > hi:
                return None
            candidates = [
                (split.at, y) for y in range(lo, hi + 1)
                if (split.at, y) not in required
            ]
            side = "east"
        if not candidates:
            return None
        x, y = rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side=side, feature="door_closed",
        )

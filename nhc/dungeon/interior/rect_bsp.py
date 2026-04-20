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
from nhc.dungeon.model import Rect, RectShape, Room


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

        target = cfg.rng.randint(3, 5)
        root = self._build_tree_to_target(
            cfg.footprint, cfg.min_room, cfg.rng,
            cfg.required_walkable, target,
        )
        leaves = self._leaves(root)
        if not leaves:
            return SingleRoomPartitioner().plan(cfg)
        if len(leaves) == 1:
            return SingleRoomPartitioner().plan(cfg)

        walls = self._collect_walls(root)
        doors = self._place_doors(root, cfg)
        for door in doors:
            walls.discard(door.xy)

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
            interior_walls=walls,
            doors=doors,
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

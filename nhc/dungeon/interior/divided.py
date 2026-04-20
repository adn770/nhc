"""Divided partitioner — two sub-rooms, one interior wall, one door.

See ``design/building_interiors.md``. Used for residential,
cottage, square tower, small farm — small footprints that read
well with a single interior division.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import Rect, RectShape, Room, canonicalize


class DividedPartitioner:
    """Split the footprint along one axis into two rooms.

    Falls back to :class:`SingleRoomPartitioner` when the footprint
    is too small to satisfy ``min_room`` on both halves.
    """

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} outside shape"
            )

        result = self._try_split(cfg)
        if result is not None:
            return result
        return SingleRoomPartitioner().plan(cfg)

    def _try_split(
        self, cfg: PartitionerConfig,
    ) -> LayoutPlan | None:
        rect = cfg.footprint
        min_room = cfg.min_room

        can_horiz = rect.height >= 2 * min_room + 1
        can_vert = rect.width >= 2 * min_room + 1
        axes: list[str] = []
        if can_horiz:
            axes.append("horizontal")
        if can_vert:
            axes.append("vertical")
        if not axes:
            return None

        # Shuffle axes so a blocked first choice doesn't force a
        # silent fallback to SingleRoom.
        cfg.rng.shuffle(axes)
        for axis in axes:
            plan = self._split_on(cfg, axis)
            if plan is not None:
                return plan
        return None

    def _split_on(
        self, cfg: PartitionerConfig, axis: str,
    ) -> LayoutPlan | None:
        rect = cfg.footprint
        min_room = cfg.min_room

        if axis == "horizontal":
            split_lo = rect.y + min_room
            split_hi = rect.y + rect.height - min_room - 1
        else:
            split_lo = rect.x + min_room
            split_hi = rect.x + rect.width - min_room - 1
        if split_lo > split_hi:
            return None

        # Try each candidate split (shuffled) until one admits a
        # door (the door tile avoids ``required_walkable``).
        splits = list(range(split_lo, split_hi + 1))
        cfg.rng.shuffle(splits)

        for split in splits:
            door = self._pick_door(cfg, axis, split)
            if door is None:
                continue
            edges = self._edge_run(rect, axis, split)
            return self._build_plan(cfg, axis, split, edges, door)
        return None

    def _edge_run(
        self, rect: Rect, axis: str, split: int,
    ) -> set[tuple[int, int, str]]:
        """Canonical edges along the split line.

        Horizontal split at ``split`` (a y-coord) emits
        ``(x, split + 1, "north")`` for every x in the footprint.
        Vertical split at ``split`` (an x-coord) emits
        ``(split + 1, y, "west")`` for every y in the footprint.
        """
        if axis == "horizontal":
            return {
                canonicalize(x, split + 1, "north")
                for x in range(rect.x, rect.x2)
            }
        return {
            canonicalize(split + 1, y, "west")
            for y in range(rect.y, rect.y2)
        }

    def _pick_door(
        self, cfg: PartitionerConfig, axis: str, split: int,
    ) -> InteriorDoor | None:
        """Pick a door tile on the un-grown side of the split.

        Horizontal: door tile ``(x, split + 1)`` with
        ``door_side="north"`` → canonical edge
        ``(x, split + 1, "north")``. Vertical: door tile
        ``(split + 1, y)`` with ``door_side="west"`` → canonical
        edge ``(split + 1, y, "west")``. The first and last tile
        of the run are excluded so the door sits on an edge run of
        ≥ 3 segments.
        """
        rect = cfg.footprint
        if axis == "horizontal":
            lo = rect.x + 1
            hi = rect.x2 - 2
            if lo > hi:
                return None
            candidates = [
                (x, split + 1) for x in range(lo, hi + 1)
                if (x, split + 1) not in cfg.required_walkable
            ]
            side = "north"
        else:
            lo = rect.y + 1
            hi = rect.y2 - 2
            if lo > hi:
                return None
            candidates = [
                (split + 1, y) for y in range(lo, hi + 1)
                if (split + 1, y) not in cfg.required_walkable
            ]
            side = "west"
        if not candidates:
            return None
        x, y = cfg.rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side=side, feature="door_closed",
        )

    def _build_plan(
        self, cfg: PartitionerConfig, axis: str, split: int,
        edges: set[tuple[int, int, str]], door: InteriorDoor,
    ) -> LayoutPlan:
        rect = cfg.footprint
        # "Top" / "left" leaf absorbs the former wall row so both
        # rooms tile the footprint.
        if axis == "horizontal":
            room_a_rect = Rect(
                rect.x, rect.y, rect.width, split + 1 - rect.y,
            )
            room_b_rect = Rect(
                rect.x, split + 1,
                rect.width, rect.y2 - split - 1,
            )
        else:
            room_a_rect = Rect(
                rect.x, rect.y, split + 1 - rect.x, rect.height,
            )
            room_b_rect = Rect(
                split + 1, rect.y,
                rect.x2 - split - 1, rect.height,
            )

        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_r0",
                rect=room_a_rect, shape=RectShape(), tags=[],
            ),
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_r1",
                rect=room_b_rect, shape=RectShape(), tags=[],
            ),
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_edges=edges,
            doors=[door],
        )

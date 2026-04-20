"""L-shape partitioner — split at the inner corner.

See ``design/building_interiors.md``. For an :class:`LShape`
footprint, a wall line runs through the inner corner along one
arm's shared edge, dividing the L into two rooms (long arm +
short arm). One door on that wall keeps them connected.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import LShape, Rect, RectShape, Room


class LShapePartitioner:
    """Split an L into long-arm and short-arm rooms."""

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} outside shape"
            )

        shape = cfg.shape
        if not isinstance(shape, LShape):
            return SingleRoomPartitioner().plan(cfg)

        min_room = cfg.min_room
        rect = cfg.footprint
        notch = shape._notch_rect(rect)

        geom = self._geometry(rect, notch, shape.corner)
        if geom is None:
            return SingleRoomPartitioner().plan(cfg)
        arm_a, arm_b, wall, door_side = geom

        if not self._arms_fit(arm_a, arm_b, min_room):
            return SingleRoomPartitioner().plan(cfg)

        if not wall.isdisjoint(cfg.required_walkable):
            return SingleRoomPartitioner().plan(cfg)

        door = self._pick_junction_door(
            wall, rect, shape.corner, cfg, door_side,
        )
        if door is None:
            return SingleRoomPartitioner().plan(cfg)
        wall.discard(door.xy)

        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_arm_a",
                rect=arm_a, shape=RectShape(),
                tags=["arm_a"],
            ),
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_arm_b",
                rect=arm_b, shape=RectShape(),
                tags=["arm_b"],
            ),
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_walls=wall,
            doors=[door],
        )

    def _geometry(
        self, rect: Rect, notch: Rect, corner: str,
    ) -> tuple[Rect, Rect, set[tuple[int, int]], str] | None:
        """Return ``(arm_a, arm_b, junction_wall, door_side)`` for
        the given L corner. Arms are the room bounding rects; the
        wall line separates them at the inner corner."""
        if corner == "nw":
            arm_a = Rect(
                notch.x2, rect.y,
                rect.x2 - notch.x2, notch.height,
            )
            arm_b = Rect(
                rect.x, notch.y2,
                rect.width, rect.y2 - notch.y2,
            )
            wall = {
                (x, notch.y2)
                for x in range(notch.x2, rect.x2)
            }
            door_side = "north"
            return arm_a, arm_b, wall, door_side
        if corner == "ne":
            arm_a = Rect(
                rect.x, rect.y,
                notch.x - rect.x, notch.height,
            )
            arm_b = Rect(
                rect.x, notch.y2,
                rect.width, rect.y2 - notch.y2,
            )
            wall = {
                (x, notch.y2)
                for x in range(rect.x, notch.x)
            }
            door_side = "north"
            return arm_a, arm_b, wall, door_side
        if corner == "sw":
            arm_a = Rect(
                rect.x, rect.y,
                rect.width, notch.y - rect.y,
            )
            arm_b = Rect(
                notch.x2, notch.y,
                rect.x2 - notch.x2, notch.height,
            )
            wall = {
                (x, notch.y)
                for x in range(notch.x2, rect.x2)
            }
            door_side = "south"
            return arm_a, arm_b, wall, door_side
        if corner == "se":
            arm_a = Rect(
                rect.x, rect.y,
                rect.width, notch.y - rect.y,
            )
            arm_b = Rect(
                rect.x, notch.y,
                notch.x - rect.x, notch.height,
            )
            wall = {
                (x, notch.y)
                for x in range(rect.x, notch.x)
            }
            door_side = "south"
            return arm_a, arm_b, wall, door_side
        return None

    def _arms_fit(
        self, arm_a: Rect, arm_b: Rect, min_room: int,
    ) -> bool:
        for arm in (arm_a, arm_b):
            if arm.width < min_room or arm.height < min_room:
                return False
        return True

    def _pick_junction_door(
        self, wall: set[tuple[int, int]], rect: Rect,
        corner: str, cfg: PartitionerConfig, door_side: str,
    ) -> InteriorDoor | None:
        """Pick a wall tile that has wall neighbours on both sides
        along the wall axis (run ≥ 3) and is not at the footprint
        edge."""
        if not wall:
            return None
        # All wall tiles share the same y (horizontal wall line).
        ys = {y for (_, y) in wall}
        if len(ys) != 1:
            return None
        wall_y = next(iter(ys))
        xs = sorted(x for (x, _) in wall)
        lo_x = xs[0]
        hi_x = xs[-1]
        candidates = [
            (x, wall_y) for x in xs
            if x != lo_x and x != hi_x
            and (x, wall_y) not in cfg.required_walkable
        ]
        if not candidates:
            return None
        x, y = cfg.rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side=door_side, feature="door_closed",
        )

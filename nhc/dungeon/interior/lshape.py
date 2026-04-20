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
from nhc.dungeon.model import (
    LShape, Rect, RectShape, Room, canonicalize,
)


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
        arm_a, arm_b, edge_xs, edge_y = geom

        if not self._arms_fit(arm_a, arm_b, min_room):
            return SingleRoomPartitioner().plan(cfg)

        door = self._pick_junction_door(
            edge_xs, edge_y, cfg,
        )
        if door is None:
            return SingleRoomPartitioner().plan(cfg)

        edges = {
            canonicalize(x, edge_y, "north") for x in edge_xs
        }

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
            interior_edges=edges,
            doors=[door],
        )

    def _geometry(
        self, rect: Rect, notch: Rect, corner: str,
    ) -> tuple[Rect, Rect, range, int] | None:
        """Return ``(arm_a, arm_b, edge_xs, edge_y)`` for the given
        L corner.

        ``edge_xs`` is the x-range (inclusive of endpoints as a
        range) and ``edge_y`` is the canonical y for the edge run:
        ``(x, edge_y, "north")`` sits between the arm above and
        the arm below. The door always targets this canonical
        edge, so ``door_side`` is always ``"north"``.
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

    def _arms_fit(
        self, arm_a: Rect, arm_b: Rect, min_room: int,
    ) -> bool:
        for arm in (arm_a, arm_b):
            if arm.width < min_room or arm.height < min_room:
                return False
        return True

    def _pick_junction_door(
        self, edge_xs: range, edge_y: int,
        cfg: PartitionerConfig,
    ) -> InteriorDoor | None:
        """Pick a door tile on arm_b's junction row.

        Door tile ``(x, edge_y)`` with ``door_side="north"``
        targets canonical edge ``(x, edge_y, "north")``. First
        and last x in the run are excluded so the door sits on a
        run of at least 3 edges.
        """
        xs = list(edge_xs)
        if len(xs) < 3:
            return None
        interior_xs = xs[1:-1]
        candidates = [
            (x, edge_y) for x in interior_xs
            if (x, edge_y) not in cfg.required_walkable
        ]
        if not candidates:
            return None
        x, y = cfg.rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side="north", feature="door_closed",
        )

"""Temple partitioner — big nave with two flanking chapels.

See ``design/building_interiors.md``. Carves two parallel walls
inside a rect footprint giving a central nave tagged ``"nave"``
and two smaller flanking chapels tagged ``"chapel"``. Each
chapel has one door into the nave.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import Rect, RectShape, Room


class TemplePartitioner:
    """Nave + two chapels layout for temple-style footprints."""

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} outside shape"
            )

        rect = cfg.footprint
        if not isinstance(cfg.shape, RectShape):
            return SingleRoomPartitioner().plan(cfg)
        min_room = cfg.min_room

        # Chapels flank the shorter axis so the nave reads long.
        if rect.width >= rect.height:
            axis = "horiz"   # chapels on east/west of the nave
            perp = rect.width
        else:
            axis = "vert"    # chapels on north/south of the nave
            perp = rect.height

        if perp < 3 * min_room + 2:
            return SingleRoomPartitioner().plan(cfg)

        chapel_size = min_room
        nave_size = perp - 2 * chapel_size - 2
        if nave_size < min_room:
            return SingleRoomPartitioner().plan(cfg)

        plan = self._build_layout(cfg, axis, chapel_size, nave_size)
        if plan is None:
            return SingleRoomPartitioner().plan(cfg)
        return plan

    def _build_layout(
        self, cfg: PartitionerConfig, axis: str,
        chapel_size: int, nave_size: int,
    ) -> LayoutPlan | None:
        rect = cfg.footprint

        if axis == "horiz":
            left_chapel = Rect(
                rect.x, rect.y, chapel_size, rect.height,
            )
            left_wall_x = rect.x + chapel_size
            nave = Rect(
                left_wall_x + 1, rect.y, nave_size, rect.height,
            )
            right_wall_x = nave.x2
            right_chapel = Rect(
                right_wall_x + 1, rect.y,
                chapel_size, rect.height,
            )
            left_wall = {
                (left_wall_x, y)
                for y in range(rect.y, rect.y2)
            }
            right_wall = {
                (right_wall_x, y)
                for y in range(rect.y, rect.y2)
            }
            left_door = self._pick_door_on_vertical_wall(
                left_wall_x, rect, cfg,
            )
            right_door = self._pick_door_on_vertical_wall(
                right_wall_x, rect, cfg,
            )
        else:
            top_chapel = Rect(
                rect.x, rect.y, rect.width, chapel_size,
            )
            top_wall_y = rect.y + chapel_size
            nave = Rect(
                rect.x, top_wall_y + 1, rect.width, nave_size,
            )
            bot_wall_y = nave.y2
            bot_chapel = Rect(
                rect.x, bot_wall_y + 1,
                rect.width, chapel_size,
            )
            left_wall = {
                (x, top_wall_y)
                for x in range(rect.x, rect.x2)
            }
            right_wall = {
                (x, bot_wall_y)
                for x in range(rect.x, rect.x2)
            }
            left_door = self._pick_door_on_horizontal_wall(
                top_wall_y, rect, cfg,
            )
            right_door = self._pick_door_on_horizontal_wall(
                bot_wall_y, rect, cfg,
            )
            left_chapel, right_chapel = top_chapel, bot_chapel

        walls = left_wall | right_wall
        if not walls.isdisjoint(cfg.required_walkable):
            return None
        if left_door is None or right_door is None:
            return None

        walls.discard(left_door.xy)
        walls.discard(right_door.xy)

        rooms = [
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_nave",
                rect=nave, shape=RectShape(),
                tags=["nave"],
            ),
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_chapel_a",
                rect=left_chapel, shape=RectShape(),
                tags=["chapel"],
            ),
            Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_chapel_b",
                rect=right_chapel, shape=RectShape(),
                tags=["chapel"],
            ),
        ]
        return LayoutPlan(
            rooms=rooms,
            interior_walls=walls,
            doors=[left_door, right_door],
        )

    def _pick_door_on_vertical_wall(
        self, wall_x: int, rect: Rect, cfg: PartitionerConfig,
    ) -> InteriorDoor | None:
        lo = rect.y + 1
        hi = rect.y2 - 2
        if lo > hi:
            return None
        candidates = [
            (wall_x, y) for y in range(lo, hi + 1)
            if (wall_x, y) not in cfg.required_walkable
        ]
        if not candidates:
            return None
        x, y = cfg.rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side="east", feature="door_closed",
        )

    def _pick_door_on_horizontal_wall(
        self, wall_y: int, rect: Rect, cfg: PartitionerConfig,
    ) -> InteriorDoor | None:
        lo = rect.x + 1
        hi = rect.x2 - 2
        if lo > hi:
            return None
        candidates = [
            (x, wall_y) for x in range(lo, hi + 1)
            if (x, wall_y) not in cfg.required_walkable
        ]
        if not candidates:
            return None
        x, y = cfg.rng.choice(candidates)
        return InteriorDoor(
            x=x, y=y, side="north", feature="door_closed",
        )

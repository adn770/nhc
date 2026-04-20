"""Sector partitioner — circle pie slices around a central hub.

See ``design/building_interiors.md``. Simple mode carves two
orthogonal radial walls (N-S and E-W) through the circle center,
producing four quadrant rooms and a central walkable hub. Each
quadrant has a door onto the hub adjacent to one of the four
radial walls.

Enriched mode (M18) adds octagon support and rotates which
sector reads as the "main" room across floors.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import CircleShape, Rect, RectShape, Room


class SectorPartitioner:
    """Split a CircleShape footprint into 4 pie-slice rooms."""

    def __init__(self, mode: str = "simple") -> None:
        if mode not in ("simple", "enriched"):
            raise ValueError(
                f"SectorPartitioner mode must be 'simple' or "
                f"'enriched'; got {mode!r}"
            )
        self.mode = mode

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} outside shape"
            )

        if not isinstance(cfg.shape, CircleShape):
            return SingleRoomPartitioner().plan(cfg)

        rect = cfg.footprint
        if rect.width != rect.height or rect.width % 2 == 0:
            return SingleRoomPartitioner().plan(cfg)

        cx = rect.x + rect.width // 2
        cy = rect.y + rect.height // 2
        hub = {(cx, cy)}

        walls: set[tuple[int, int]] = set()
        for (x, y) in floor_tiles:
            if x == cx or y == cy:
                walls.add((x, y))
        walls -= hub

        # Check required_walkable doesn't fall on walls.
        if not walls.isdisjoint(cfg.required_walkable):
            return SingleRoomPartitioner().plan(cfg)

        doors = self._place_cardinal_doors(cx, cy, walls, cfg)
        door_xys = {d.xy for d in doors}
        if door_xys & cfg.required_walkable:
            return SingleRoomPartitioner().plan(cfg)
        walls -= door_xys

        rooms = self._build_sector_rooms(cfg, rect, cx, cy)
        return LayoutPlan(
            rooms=rooms,
            interior_walls=walls,
            doors=doors,
        )

    def _place_cardinal_doors(
        self, cx: int, cy: int,
        walls: set[tuple[int, int]], cfg: PartitionerConfig,
    ) -> list[InteriorDoor]:
        """One door adjacent to the hub on each cardinal wall tile
        that is inside the circle."""
        candidates = [
            (cx, cy - 1, "north"),
            (cx, cy + 1, "south"),
            (cx - 1, cy, "west"),
            (cx + 1, cy, "east"),
        ]
        doors: list[InteriorDoor] = []
        for (x, y, side) in candidates:
            if (x, y) not in walls:
                continue
            if (x, y) in cfg.required_walkable:
                continue
            doors.append(InteriorDoor(
                x=x, y=y, side=side, feature="door_closed",
            ))
        return doors

    def _build_sector_rooms(
        self, cfg: PartitionerConfig, rect: Rect,
        cx: int, cy: int,
    ) -> list[Room]:
        """Four quadrant rooms. Rects are approximate bounding
        boxes; walkable tile set is determined by the level's
        terrain at render time."""
        quads = [
            ("nw", rect.x, cx - 1, rect.y, cy - 1),
            ("ne", cx + 1, rect.x2 - 1, rect.y, cy - 1),
            ("sw", rect.x, cx - 1, cy + 1, rect.y2 - 1),
            ("se", cx + 1, rect.x2 - 1, cy + 1, rect.y2 - 1),
        ]
        rooms: list[Room] = []
        for i, (label, xmin, xmax, ymin, ymax) in enumerate(quads):
            room_rect = Rect(
                xmin, ymin,
                max(1, xmax - xmin + 1),
                max(1, ymax - ymin + 1),
            )
            rooms.append(Room(
                id=f"{cfg.archetype}_f{cfg.floor_index}_{label}",
                rect=room_rect,
                shape=RectShape(),
                tags=["sector", label],
            ))
        return rooms

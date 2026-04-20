"""Sector partitioner — axis splits through a circle / octagon.

See ``design/building_interiors.md``. Simple mode picks one of
``{"vert", "horiz", "cross"}`` axes through the footprint centre.
A vertical or horizontal split yields two rooms; a cross split
yields four. Edges are canonical, intersected with the
footprint's walkable tiles so they never dangle over VOID.

Enriched mode is deterministic: axis cycles as
``floor_index % 3`` (vert, horiz, cross, vert, …). One door is
omitted on every even floor to give the tower a spiral reading.
One room per floor is tagged ``"main"`` for the stair picker.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    InteriorDoor, LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import (
    CircleShape, OctagonShape, Rect, RectShape, Room, canonicalize,
)


_AXES = ("vert", "horiz", "cross")


class SectorPartitioner:
    """Axis-split partitioner for circle / octagon footprints."""

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

        if not isinstance(cfg.shape, (CircleShape, OctagonShape)):
            return SingleRoomPartitioner().plan(cfg)

        rect = cfg.footprint
        if rect.width != rect.height or rect.width % 2 == 0:
            return SingleRoomPartitioner().plan(cfg)

        cx = rect.x + rect.width // 2
        cy = rect.y + rect.height // 2

        axis = self._pick_axis(cfg)
        rooms = self._build_rooms(cfg, axis, cx, cy)
        edges = self._build_edges(axis, cx, cy, rect, floor_tiles)
        doors = self._build_doors(axis, cx, cy, cfg)
        if any(d is None for d in doors):
            return SingleRoomPartitioner().plan(cfg)
        doors = [d for d in doors if d is not None]

        if self.mode == "enriched":
            self._tag_main_room(rooms, cfg.floor_index)
            doors = self._omit_alternating_door(doors, cfg)

        return LayoutPlan(
            rooms=rooms,
            interior_edges=edges,
            doors=doors,
        )

    def _pick_axis(self, cfg: PartitionerConfig) -> str:
        if self.mode == "enriched":
            return _AXES[cfg.floor_index % len(_AXES)]
        return cfg.rng.choice(_AXES)

    def _build_rooms(
        self, cfg: PartitionerConfig, axis: str,
        cx: int, cy: int,
    ) -> list[Room]:
        """Disjoint rect leaves covering the footprint's bounding
        box. The right / bottom leaf absorbs the centre column /
        row so there are no un-owned tiles on the split line."""
        rect = cfg.footprint
        floor = cfg.floor_index
        arch = cfg.archetype

        def _room(
            idx: int, label: str, r: Rect,
        ) -> Room:
            return Room(
                id=f"{arch}_f{floor}_{label}",
                rect=r,
                shape=RectShape(),
                tags=["sector", label],
            )

        if axis == "vert":
            left = Rect(rect.x, rect.y, cx - rect.x, rect.height)
            right = Rect(cx, rect.y, rect.x2 - cx, rect.height)
            return [_room(0, "left", left), _room(1, "right", right)]
        if axis == "horiz":
            top = Rect(rect.x, rect.y, rect.width, cy - rect.y)
            bot = Rect(rect.x, cy, rect.width, rect.y2 - cy)
            return [_room(0, "top", top), _room(1, "bot", bot)]
        # cross: NW, NE, SW, SE — right / bottom quadrants absorb
        # the centre column / row.
        nw = Rect(rect.x, rect.y, cx - rect.x, cy - rect.y)
        ne = Rect(cx, rect.y, rect.x2 - cx, cy - rect.y)
        sw = Rect(rect.x, cy, cx - rect.x, rect.y2 - cy)
        se = Rect(cx, cy, rect.x2 - cx, rect.y2 - cy)
        return [
            _room(0, "nw", nw),
            _room(1, "ne", ne),
            _room(2, "sw", sw),
            _room(3, "se", se),
        ]

    def _build_edges(
        self, axis: str, cx: int, cy: int, rect: Rect,
        floor_tiles: set[tuple[int, int]],
    ) -> set[tuple[int, int, str]]:
        """Canonical edges along the split line(s), clipped to the
        footprint (both adjacent tiles must be floor)."""
        edges: set[tuple[int, int, str]] = set()
        if axis in ("vert", "cross"):
            for y in range(rect.y, rect.y2):
                if (cx - 1, y) in floor_tiles and (cx, y) in floor_tiles:
                    edges.add(canonicalize(cx, y, "west"))
        if axis in ("horiz", "cross"):
            for x in range(rect.x, rect.x2):
                if (x, cy - 1) in floor_tiles and (x, cy) in floor_tiles:
                    edges.add(canonicalize(x, cy, "north"))
        return edges

    def _build_doors(
        self, axis: str, cx: int, cy: int,
        cfg: PartitionerConfig,
    ) -> list[InteriorDoor | None]:
        """Door placement near the footprint centre.

        - vert: one door at ``(cx-1, cy)`` side ``"east"``
          suppressing edge ``(cx, cy, "west")``.
        - horiz: one door at ``(cx, cy-1)`` side ``"south"``
          suppressing edge ``(cx, cy, "north")``.
        - cross: three doors forming a minimum spanning tree over
          the four quadrants: NW↔NE at ``(cx-1, cy-1)`` "east",
          NW↔SW at ``(cx-1, cy)`` "north", NE↔SE at
          ``(cx, cy-1)`` "south".

        Any conflict with ``required_walkable`` returns ``None``
        for that door; callers treat a ``None`` in the result as a
        hard fallback to ``SingleRoomPartitioner``.
        """
        req = cfg.required_walkable
        doors: list[InteriorDoor | None] = []

        def _door(
            x: int, y: int, side: str,
        ) -> InteriorDoor | None:
            if (x, y) in req:
                return None
            return InteriorDoor(
                x=x, y=y, side=side, feature="door_closed",
            )

        if axis == "vert":
            doors.append(_door(cx - 1, cy, "east"))
        elif axis == "horiz":
            doors.append(_door(cx, cy - 1, "south"))
        else:  # cross
            doors.append(_door(cx - 1, cy - 1, "east"))
            doors.append(_door(cx - 1, cy, "north"))
            doors.append(_door(cx, cy - 1, "south"))
        return doors

    def _omit_alternating_door(
        self, doors: list[InteriorDoor],
        cfg: PartitionerConfig,
    ) -> list[InteriorDoor]:
        """Drop one door on every even-indexed floor. The dropped
        index rotates with ``floor_index`` so the spiral pattern
        stays fresh across the stack."""
        if cfg.floor_index % 2 != 0 or not doors:
            return doors
        if len(doors) < 2:
            return doors
        drop = cfg.floor_index % len(doors)
        return [d for i, d in enumerate(doors) if i != drop]

    def _tag_main_room(
        self, rooms: list[Room], floor_index: int,
    ) -> None:
        """Tag one room as ``"main"`` per floor, rotating by
        ``floor_index``. Stair pickers use this hint."""
        if not rooms:
            return
        main = floor_index % len(rooms)
        rooms[main].tags.append("main")

"""Partitioner protocol and shared dataclasses.

See ``design/building_interiors.md`` section "Partitioner API".
Partitioners never touch a ``Level`` directly — they return a
description the site floor builder stamps.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from nhc.dungeon.model import Rect, Room, RoomShape


@dataclass(frozen=True)
class PartitionerConfig:
    """Caller-supplied config for a :class:`Partitioner`.

    ``required_walkable`` tiles MUST already be members of
    ``shape.floor_tiles(footprint)``. Partitioners assert this at
    entry and never silently relocate tiles — it's a caller bug,
    not a runtime recoverable condition.
    """

    footprint: Rect
    shape: RoomShape
    floor_index: int
    n_floors: int
    rng: random.Random
    archetype: str
    required_walkable: frozenset[tuple[int, int]] = frozenset()
    min_room: int = 3
    padding: int = 1
    corridor_width: int = 1


@dataclass
class InteriorDoor:
    """A door emitted by a partitioner for the site to stamp."""

    x: int
    y: int
    side: str       # "north" / "south" / "east" / "west"
    feature: str    # "door_closed" | "door_locked"

    @property
    def xy(self) -> tuple[int, int]:
        return (self.x, self.y)


@dataclass
class LayoutPlan:
    """Partitioner output.

    Disjointness invariants (checked in tests, never silently
    patched at runtime):

    - ``interior_walls`` ∩ ``{d.xy for d in doors}`` == ∅
    - ``interior_walls`` ∩ ``corridor_tiles`` == ∅
    - ``interior_walls`` ∩ ``cfg.required_walkable`` == ∅
    - ``{d.xy for d in doors}`` ∩ ``cfg.required_walkable`` == ∅
    """

    rooms: list[Room]
    interior_walls: set[tuple[int, int]] = field(default_factory=set)
    corridor_tiles: set[tuple[int, int]] = field(default_factory=set)
    doors: list[InteriorDoor] = field(default_factory=list)


class Partitioner(Protocol):
    """Layout planner for a single building floor."""

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        ...

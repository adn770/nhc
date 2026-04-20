"""Single-room partitioner.

Reproduces the pre-M2 floor layout: one room spanning the full
footprint, no interior walls, no corridors, no doors. Used for
small / fallback archetypes (ruin, stable) and as the routing
target for M3-M4 before richer partitioners land.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import (
    LayoutPlan, PartitionerConfig,
)
from nhc.dungeon.model import Rect, Room


class SingleRoomPartitioner:
    """Emit one room covering the whole footprint."""

    def plan(self, cfg: PartitionerConfig) -> LayoutPlan:
        floor_tiles = cfg.shape.floor_tiles(cfg.footprint)
        for tile in cfg.required_walkable:
            assert tile in floor_tiles, (
                f"required_walkable tile {tile} is outside "
                f"shape.floor_tiles(footprint)"
            )

        room = Room(
            id=f"{cfg.archetype}_f{cfg.floor_index}_room",
            rect=Rect(
                cfg.footprint.x, cfg.footprint.y,
                cfg.footprint.width, cfg.footprint.height,
            ),
            shape=cfg.shape,
            tags=[],
        )
        return LayoutPlan(rooms=[room])

"""Stamp a :class:`LayoutPlan` onto a :class:`Level`.

Site floor builders call this after a partitioner returns.
Partitioning is expressed entirely as edges and doors — no tile
becomes a WALL inside the footprint. The shell composer owns
footprint walls, which live outside this path.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import LayoutPlan
from nhc.dungeon.model import Level, SurfaceType, Terrain


_CANONICAL_EDGE_SIDES = ("north", "west")


def apply_plan(level: Level, plan: LayoutPlan) -> None:
    """Stamp a LayoutPlan onto a Level.

    Order: interior edges → corridor tile surface types → doors.
    """
    for (x, y, side) in plan.interior_edges:
        assert side in _CANONICAL_EDGE_SIDES, (
            f"LayoutPlan edge ({x}, {y}, {side!r}) is not canonical; "
            "partitioner must normalize via canonicalize()"
        )

    level.interior_edges.update(plan.interior_edges)
    for (x, y) in plan.corridor_tiles:
        tile = level.tiles[y][x]
        tile.surface_type = SurfaceType.CORRIDOR
    for door in plan.doors:
        tile = level.tiles[door.y][door.x]
        tile.terrain = Terrain.FLOOR
        tile.feature = door.feature
        tile.door_side = door.side

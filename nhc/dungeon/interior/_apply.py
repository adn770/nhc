"""Stamp a :class:`LayoutPlan` onto a :class:`Level`.

Site floor builders call this after a partitioner returns. Keeps
the stamping order consistent across every archetype so a future
partitioner that emits walls under a corridor or a door lands on
a loud assertion rather than silent precedence ambiguity.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import LayoutPlan
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile


def apply_plan(level: Level, plan: LayoutPlan) -> None:
    """Stamp ``plan.interior_walls`` as WALL, corridor tiles as
    :attr:`SurfaceType.CORRIDOR`, and doors as FLOOR with the
    door feature + ``door_side`` metadata."""
    doors_xy = {d.xy for d in plan.doors}
    assert plan.interior_walls.isdisjoint(doors_xy), (
        "LayoutPlan invariant: interior_walls must not overlap doors"
    )
    assert plan.interior_walls.isdisjoint(plan.corridor_tiles), (
        "LayoutPlan invariant: interior_walls must not overlap "
        "corridor tiles"
    )

    for (x, y) in plan.interior_walls:
        level.tiles[y][x] = Tile(terrain=Terrain.WALL)
    for (x, y) in plan.corridor_tiles:
        tile = level.tiles[y][x]
        tile.surface_type = SurfaceType.CORRIDOR
    for door in plan.doors:
        tile = level.tiles[door.y][door.x]
        tile.terrain = Terrain.FLOOR
        tile.feature = door.feature
        tile.door_side = door.side

"""Stamp a :class:`LayoutPlan` onto a :class:`Level`.

Site floor builders call this after a partitioner returns. Keeps
the stamping order consistent across every archetype so a future
partitioner that emits walls under a corridor or a door lands on
a loud assertion rather than silent precedence ambiguity.
"""

from __future__ import annotations

from nhc.dungeon.interior.protocol import LayoutPlan
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile


_CANONICAL_EDGE_SIDES = ("north", "west")


def apply_plan(level: Level, plan: LayoutPlan) -> None:
    """Stamp a LayoutPlan onto a Level.

    Order: interior edges → interior tile walls (legacy) →
    corridor tile surface types → doors. Edges and tile walls both
    describe wall geometry today, but the edge form is the
    long-term primitive — M12 removes the tile form.
    """
    doors_xy = {d.xy for d in plan.doors}
    assert plan.interior_walls.isdisjoint(doors_xy), (
        "LayoutPlan invariant: interior_walls must not overlap doors"
    )
    assert plan.interior_walls.isdisjoint(plan.corridor_tiles), (
        "LayoutPlan invariant: interior_walls must not overlap "
        "corridor tiles"
    )
    for (x, y, side) in plan.interior_edges:
        assert side in _CANONICAL_EDGE_SIDES, (
            f"LayoutPlan edge ({x}, {y}, {side!r}) is not canonical; "
            "partitioner must normalize via canonicalize()"
        )

    level.interior_edges.update(plan.interior_edges)
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

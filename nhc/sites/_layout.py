"""Renderable bbox helpers for the level surface contract.

Every level-producing generator (site assembler, dungeon /
template / underworld pipeline, building floor builder) is
expected to leave a 1-tile VOID margin between the renderable
content and the canvas edge — see
``design/level_surface_layout.md`` for the contract.

The renderable bbox is the union of:

1. Non-VOID tiles in ``level.tiles``.
2. The enclosure polygon's tile span (``site.enclosure``), when
   present. Polygon vertices are edge coordinates: a vertex at
   ``x`` sits on the left edge of tile column ``x``, so the
   polygon's tile contribution is ``[min_vertex, max_vertex - 1]``
   on each axis.
3. Each ``building.base_rect`` grown by 1 tile on every side to
   capture decoration overhang (roof eaves, vegetation cling,
   shadows that paint outside the footprint).

The contract is satisfied when ``min ≥ 1`` and ``max ≤ size - 2``
on each axis (1-tile VOID margin on every side).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nhc.dungeon.model import Terrain

if TYPE_CHECKING:
    from nhc.dungeon.model import Level
    from nhc.sites._site import Site


@dataclass(frozen=True)
class RenderableBBox:
    """Inclusive integer bbox enclosing every renderable element."""

    min_x: int
    min_y: int
    max_x: int
    max_y: int

    @property
    def empty(self) -> bool:
        return self.max_x < self.min_x or self.max_y < self.min_y


def compute_renderable_bbox(
    level: "Level", site: "Site | None" = None,
) -> RenderableBBox:
    """Return the inclusive bbox of every renderable element.

    Walks ``level.tiles`` for non-VOID terrain, the enclosure
    polygon (treated as edge coordinates: tile span shrinks by 1
    at each max edge), and every building's ``base_rect`` grown
    by 1 tile on every side to capture decoration overhang.

    Empty levels (all VOID, no site) return an explicit "empty"
    bbox where ``max < min``; callers should treat that as a
    contract violation.
    """
    min_x = 1 << 30
    min_y = 1 << 30
    max_x = -(1 << 30)
    max_y = -(1 << 30)

    for y in range(level.height):
        row = level.tiles[y]
        for x in range(level.width):
            if row[x].terrain is Terrain.VOID:
                continue
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y

    if site is not None:
        if site.enclosure is not None and site.enclosure.polygon:
            xs = [p[0] for p in site.enclosure.polygon]
            ys = [p[1] for p in site.enclosure.polygon]
            poly_min_x = min(xs)
            poly_min_y = min(ys)
            poly_max_x = max(xs) - 1
            poly_max_y = max(ys) - 1
            if poly_min_x < min_x:
                min_x = poly_min_x
            if poly_min_y < min_y:
                min_y = poly_min_y
            if poly_max_x > max_x:
                max_x = poly_max_x
            if poly_max_y > max_y:
                max_y = poly_max_y
        for b in site.buildings:
            r = b.base_rect
            if r.x - 1 < min_x:
                min_x = r.x - 1
            if r.y - 1 < min_y:
                min_y = r.y - 1
            if r.x2 > max_x:
                max_x = r.x2
            if r.y2 > max_y:
                max_y = r.y2

    return RenderableBBox(min_x, min_y, max_x, max_y)

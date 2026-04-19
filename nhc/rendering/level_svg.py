"""Entry point that renders any Level to SVG.

Dispatches between :func:`render_floor_svg` (plain dungeon floors,
surfaces) and :func:`render_building_floor_svg` (Building interior
floors that want a brick / stone perimeter overlay).  Centralised
so every call site -- web client floor-change pushes, resume, and
session bootstrap -- picks the right renderer without duplicating
the branch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.rendering.building import render_building_floor_svg
from nhc.rendering.svg import render_floor_svg

if TYPE_CHECKING:
    from nhc.dungeon.model import Level
    from nhc.dungeon.site import Site


def render_level_svg(
    level: "Level",
    site: "Site | None" = None,
    *,
    seed: int = 0,
    hatch_distance: float = 2.0,
) -> str:
    """Return the SVG string for ``level``.

    When ``level.building_id`` is set and matches a building on
    ``site``, render the composite Building floor (base SVG plus
    brick/stone wall overlay). Otherwise fall back to the plain
    floor renderer so dungeons and Site surfaces keep the same
    output byte-for-byte.
    """
    if (
        site is not None
        and getattr(level, "building_id", None) is not None
        and level.floor_index is not None
    ):
        for b in site.buildings:
            if b.id == level.building_id:
                return render_building_floor_svg(
                    b, level.floor_index, seed=seed,
                )
    return render_floor_svg(
        level, seed=seed, hatch_distance=hatch_distance,
    )

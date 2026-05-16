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

import logging

from nhc.rendering.building import render_building_floor_svg
from nhc.rendering.site_svg import render_site_surface_svg
from nhc.rendering.svg import render_floor_svg

if TYPE_CHECKING:
    from nhc.dungeon.model import Level
    from nhc.sites._site import Site


logger = logging.getLogger(__name__)


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
    brick/stone wall overlay). When the Level *is* the site's
    surface, compose roofs + (town/keep) enclosure on top of the
    bare floor SVG. Otherwise fall back to the plain floor
    renderer so dungeon floors keep the same output byte-for-byte.
    """
    if site is not None:
        if (
            getattr(level, "building_id", None) is not None
            and level.floor_index is not None
        ):
            for b in site.buildings:
                if b.id == level.building_id:
                    logger.debug(
                        "render-level-svg: branch=building "
                        "level=%s building=%s floor=%s",
                        level.id, b.id, level.floor_index,
                    )
                    return render_building_floor_svg(
                        b, level.floor_index, seed=seed,
                    )
        if level is site.surface:
            logger.debug(
                "render-level-svg: branch=site_surface "
                "level=%s site=%s",
                level.id, site.kind,
            )
            return render_site_surface_svg(
                site, seed=seed,
            )
    logger.debug(
        "render-level-svg: branch=plain_floor level=%s "
        "has_site=%s building_id=%s floor_index=%s",
        level.id, site is not None,
        getattr(level, "building_id", None),
        getattr(level, "floor_index", None),
    )
    return render_floor_svg(
        level, seed=seed, hatch_distance=hatch_distance,
    )

"""Site-surface SVG composition.

The game's web client used to render a bare floor SVG for every
site-surface Level -- streets and void footprints, nothing else.
``render_site_surface_svg`` layers the full set of production
overlays on top:

* shingle rooftops per non-circle building (every site kind)
* palisade or fortification walls (``town`` and ``keep`` only,
  per the Q5 scope decision in the site-surface rendering plan)

Doors deliberately stay out of the SVG: the web / console
clients render them directly from ``Tile.door_side`` metadata.

The composition matches what ``tests/samples/generate_svg.py``
has been producing for months; M5 wires it through the production
pipeline so the in-game view catches up to the sample tooling.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from nhc.rendering._enclosures import (
    render_fortification_enclosure,
    render_palisade_enclosure,
)
from nhc.rendering._roofs import building_roof_fragments
from nhc.rendering._svg_helpers import CELL, PADDING
from nhc.rendering.svg import render_floor_svg

if TYPE_CHECKING:
    from nhc.sites._site import Site


logger = logging.getLogger(__name__)

_OPEN_TAG = re.compile(r"<[a-zA-Z]")


def _stats_comment(name: str, fragments: list[str]) -> tuple[str, int, int]:
    """Return ``(comment, n_elements, n_bytes)`` for ``fragments``.

    Mirrors the layer-stats comment emitted by
    :func:`nhc.rendering._pipeline.render_layers` so the site
    overlays read the same way as the floor layers in a captured
    SVG.
    """
    joined = "".join(fragments)
    n_elements = len(_OPEN_TAG.findall(joined))
    n_bytes = len(joined)
    return (
        f"<!-- layer.{name}: {n_elements} elements, "
        f"{n_bytes} bytes -->",
        n_elements,
        n_bytes,
    )


# Kinds whose enclosure geometry is currently well-defined in
# nhc.rendering._enclosures. Ruin carries a "broken fortification"
# concept that needs its own geometry; cottage / temple have no
# enclosure at all.
_ENCLOSURE_KINDS = frozenset({"town", "keep"})


def _enclosure_fragments(site: "Site", seed: int) -> list[str]:
    """Project ``Site.enclosure`` (tile-coord polygon + tile-space
    gates) into the parametric (edge_index, t_center, half_len_px)
    form the enclosure renderers expect. Returns ``[]`` when the
    site has no enclosure or belongs to a kind we don't cover yet.
    """
    if site.enclosure is None:
        return []
    if site.kind not in _ENCLOSURE_KINDS:
        return []

    poly_px = [
        (PADDING + x * CELL, PADDING + y * CELL)
        for (x, y) in site.enclosure.polygon
    ]

    gates_param: list[tuple[int, float, float]] = []
    for (gx, gy, length_tiles) in site.enclosure.gates:
        gx_px = PADDING + gx * CELL
        gy_px = PADDING + gy * CELL
        best_idx = 0
        best_d = float("inf")
        best_t = 0.5
        for i in range(len(poly_px)):
            ax, ay = poly_px[i]
            bx, by = poly_px[(i + 1) % len(poly_px)]
            dx, dy = bx - ax, by - ay
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq == 0:
                continue
            t = max(0.0, min(1.0, (
                (gx_px - ax) * dx + (gy_px - ay) * dy
            ) / seg_len_sq))
            px = ax + dx * t
            py = ay + dy * t
            d = (px - gx_px) ** 2 + (py - gy_px) ** 2
            if d < best_d:
                best_d = d
                best_idx = i
                best_t = t
        gates_param.append(
            (best_idx, best_t, length_tiles * CELL / 2)
        )

    if site.enclosure.kind == "fortification":
        return list(render_fortification_enclosure(
            poly_px, gates=gates_param,
        ))
    if site.enclosure.kind == "palisade":
        return list(render_palisade_enclosure(
            poly_px, gates=gates_param, seed=seed,
        ))
    return []


def render_site_surface_svg(
    site: "Site", seed: int = 0, *, vegetation: bool = True,
) -> str:
    """Return the web-ready SVG for ``site.surface`` with roofs
    and (for ``town`` / ``keep``) an enclosure ring composed on
    top of the floor layer. Doors are not drawn -- the web client
    renders them from ``Tile.door_side`` metadata.

    Both the roof and enclosure passes carry the same stats-
    comment annotation as the floor layers (see
    :func:`nhc.rendering._pipeline.render_layers`) so a captured
    site SVG reports the size of every contributing pass inline.

    ``vegetation=False`` skips the tree + bush surface decorators;
    use it for the in-game web client where the static SVG only
    needs to ship the structural floor and animated overlays
    handle decoration. Sample tooling and golden snapshots keep
    the default ``True`` so vegetation regression coverage stays
    intact.
    """
    base = render_floor_svg(
        site.surface, seed=seed, vegetation=vegetation,
    )
    roof_frags = list(building_roof_fragments(site, seed))
    encl_frags = list(_enclosure_fragments(site, seed))
    overlay_parts: list[str] = []
    breakdown: list[tuple[str, int, int]] = []
    if roof_frags:
        comment, n_el, n_bytes = _stats_comment("roofs", roof_frags)
        overlay_parts.append(comment)
        overlay_parts.extend(roof_frags)
        breakdown.append(("roofs", n_el, n_bytes))
    if encl_frags:
        comment, n_el, n_bytes = _stats_comment(
            "enclosure", encl_frags,
        )
        overlay_parts.append(comment)
        overlay_parts.extend(encl_frags)
        breakdown.append(("enclosure", n_el, n_bytes))
    if breakdown and logger.isEnabledFor(logging.DEBUG):
        per = " ".join(
            f"{name}={b}b/{n}el" for name, n, b in breakdown
        )
        logger.debug(
            "render_site_surface_svg: site=%s overlays [%s]",
            site.kind, per,
        )
    if not overlay_parts:
        return base
    return base.replace("</svg>", "".join(overlay_parts) + "</svg>")

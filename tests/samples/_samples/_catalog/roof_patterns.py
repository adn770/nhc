"""Roof tile-pattern catalog page — 5 patterns x 3 base shapes.

Pinned to Pyramid style (the production default for square /
octagon / circle footprints) so the per-pattern texture overlay
reads against the same per-side palette shading in every cell.
"""

from __future__ import annotations

from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, roof_factory,
)


register_catalog_page(CatalogPageSpec(
    name="patterns",
    category="synthetic/roofs",
    description=(
        "Five RoofTilePattern overlays - Plain, Fishscale, "
        "Thatch, Pantile, Slate - layered on the production-"
        "default Pyramid geometry across rect / octagon / circle "
        "footprints. Plain is byte-identical to the legacy "
        "no-overlay output; the four texture overlays paint on "
        "top of the per-side palette so the pyramid silhouette "
        "stays visible behind the tile pattern."
    ),
    columns=[
        ColumnSpec(
            "Plain",
            roof_factory(
                style=RoofStyle.Pyramid,
                sub_pattern=RoofTilePattern.Plain,
            ),
        ),
        ColumnSpec(
            "Fishscale",
            roof_factory(
                style=RoofStyle.Pyramid,
                sub_pattern=RoofTilePattern.Fishscale,
            ),
        ),
        ColumnSpec(
            "Thatch",
            roof_factory(
                style=RoofStyle.Pyramid,
                sub_pattern=RoofTilePattern.Thatch,
            ),
        ),
        ColumnSpec(
            "Pantile",
            roof_factory(
                style=RoofStyle.Pyramid,
                sub_pattern=RoofTilePattern.Pantile,
            ),
        ),
        ColumnSpec(
            "Slate",
            roof_factory(
                style=RoofStyle.Pyramid,
                sub_pattern=RoofTilePattern.Slate,
            ),
        ),
    ],
    seed=7,
    params={"axis": "roof-tile-patterns"},
))


__all__ = []

"""Roof catalog page — 5 roof styles × 3 base shapes."""

from __future__ import annotations

from nhc.rendering.ir._fb.RoofStyle import RoofStyle

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, roof_factory,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/roofs",
    description=(
        "Five RoofStyle variants — Simple, Pyramid, Gable, Dome, "
        "WitchHat — across rect / octagon / circle base shapes. "
        "Each cell pairs the cell-shape region with a RoofOp; the "
        "roof painter walks the region outline to synthesise the "
        "roof silhouette."
    ),
    columns=[
        ColumnSpec("Simple", roof_factory(style=RoofStyle.Simple)),
        ColumnSpec("Pyramid", roof_factory(style=RoofStyle.Pyramid)),
        ColumnSpec("Gable", roof_factory(style=RoofStyle.Gable)),
        ColumnSpec("Dome", roof_factory(style=RoofStyle.Dome)),
        ColumnSpec("WitchHat", roof_factory(style=RoofStyle.WitchHat)),
    ],
    seed=7,
    params={"axis": "roof-styles"},
))


__all__ = []

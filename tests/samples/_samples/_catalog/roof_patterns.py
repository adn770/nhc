"""Roof catalog page — full styles × patterns matrix.

A 4 × 4 grid: every ``RoofStyle`` (rows) crossed with every
``RoofTilePattern`` (columns), all on a fixed rect footprint so
the only variables per cell are the geometry and its texture
overlay. This makes every (style, pattern) combination visible
and regression-checked, replacing the historical Pyramid-only
patterns page (``design/roof_patterns.md`` § Catalog).
"""

from __future__ import annotations

from nhc.rendering.ir._fb.RoofStyle import RoofStyle
from nhc.rendering.ir._fb.RoofTilePattern import RoofTilePattern

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, roof_matrix_factory,
)


# Row axis — one RoofStyle per row (label IS the row, cell_shape
# pins the footprint so geometry is the only row variable).
_STYLE_ROWS: tuple[tuple[str, int], ...] = (
    ("Simple", RoofStyle.Simple),
    ("Pyramid", RoofStyle.Pyramid),
    ("Gable", RoofStyle.Gable),
    ("Dome", RoofStyle.Dome),
)
_ROW_LABELS = tuple(name for name, _ in _STYLE_ROWS)
_ROW_STYLES = [style for _, style in _STYLE_ROWS]


def _col(label: str, pattern: int) -> ColumnSpec:
    return ColumnSpec(
        label,
        roof_matrix_factory(sub_pattern=pattern, styles=_ROW_STYLES),
    )


register_catalog_page(CatalogPageSpec(
    name="patterns",
    category="synthetic/roofs",
    description=(
        "Styles x patterns matrix - every RoofStyle (rows: "
        "Simple, Pyramid, Gable, Dome) crossed with every "
        "RoofTilePattern (columns: Shingle, Fishscale, Thatch, "
        "Slate) on a fixed rect footprint. Each pattern "
        "is oriented in the geometry's plane-local frame (gable "
        "mirrors across the ridge, pyramid rotates per facet, "
        "dome follows concentric rings); Shingle is the organic "
        "running-bond default."
    ),
    columns=[
        _col("Shingle", RoofTilePattern.Shingle),
        _col("Fishscale", RoofTilePattern.Fishscale),
        _col("Thatch", RoofTilePattern.Thatch),
        _col("Slate", RoofTilePattern.Slate),
    ],
    rows=_ROW_LABELS,
    cell_shape="rect",
    seed=7,
    params={"axis": "roof-styles-x-patterns"},
))


__all__ = []

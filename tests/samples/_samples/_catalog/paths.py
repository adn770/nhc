"""Path catalog page — 2 PathStyle variants × 3 shapes."""

from __future__ import annotations

from nhc.rendering.ir._fb.PathStyle import PathStyle

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    path_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/paths",
    description=(
        "PathStyle variants — CartTracks, OreVein — across rect / "
        "octagon / circle shape rows. Each cell paints a Plain base "
        "then walks a horizontal stripe of tiles through the cell "
        "centre via PathOp; the Rust path painter resolves the "
        "4-neighbour topology to the matching corner / T-junction "
        "stamps."
    ),
    columns=[
        ColumnSpec("CartTracks", path_factory(style=PathStyle.CartTracks)),
        ColumnSpec("OreVein", path_factory(style=PathStyle.OreVein)),
    ],
    seed=7,
    params={"axis": "path-styles"},
))


__all__ = []

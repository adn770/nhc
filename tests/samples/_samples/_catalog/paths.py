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


# ── Post-Phase-5 deferred-polish path styles ──────────────────


register_catalog_page(CatalogPageSpec(
    name="styles-extra",
    category="synthetic/paths",
    description=(
        "PathStyle post-Phase-5 additions — RailLine (clean grey "
        "steel rail per tile, derived from open-sides connectivity), "
        "Vines (per-tile sinuous green tendrils via quadratic "
        "splines), RootSystem (3-4 short brown tendrils per tile), "
        "RiverBed (translucent blue tile fill + ripple stroke), "
        "LavaSeam (bright orange core + deep-red glow stroke pair "
        "per tile) — across rect / octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("RailLine", path_factory(style=PathStyle.RailLine)),
        ColumnSpec("Vines", path_factory(style=PathStyle.Vines)),
        ColumnSpec("RootSystem", path_factory(style=PathStyle.RootSystem)),
        ColumnSpec("RiverBed", path_factory(style=PathStyle.RiverBed)),
        ColumnSpec("LavaSeam", path_factory(style=PathStyle.LavaSeam)),
    ],
    seed=7,
    params={"axis": "path-styles-extra"},
))


__all__ = []

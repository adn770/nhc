"""Plain floor catalog page — 1 style × 3 shapes (sanity baseline)."""

from __future__ import annotations

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    plain_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="default",
    category="synthetic/floors/plain",
    description=(
        "Plain substrate — single white fill (DungeonFloor) across "
        "rect / octagon / circle shape rows. Painter sanity "
        "baseline; pins the dispatch contract for the smallest "
        "Material family."
    ),
    columns=[
        ColumnSpec("Plain", plain_factory()),
    ],
    seed=7,
    params={"family": "Plain"},
))


__all__ = []

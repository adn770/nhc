"""Cave floor catalog page — 4 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    CAVE_BASALT, CAVE_GRANITE, CAVE_LIMESTONE, CAVE_SANDSTONE,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    cave_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/floors/cave",
    description=(
        "Cave substrates — Limestone, Granite, Sandstone, Basalt — "
        "across rect / octagon / circle shape rows. Each style "
        "carries its (base, highlight, shadow) palette over the "
        "buffered-jittered cave-outline pipeline."
    ),
    columns=[
        ColumnSpec("Limestone", cave_factory(style=CAVE_LIMESTONE)),
        ColumnSpec("Granite", cave_factory(style=CAVE_GRANITE)),
        ColumnSpec("Sandstone", cave_factory(style=CAVE_SANDSTONE)),
        ColumnSpec("Basalt", cave_factory(style=CAVE_BASALT)),
    ],
    seed=7,
    params={"family": "Cave"},
))


__all__ = []

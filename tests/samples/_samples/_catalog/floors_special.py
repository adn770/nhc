"""Special floor catalog page — 4 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    SPECIAL_ABYSS, SPECIAL_CHASM, SPECIAL_PIT, SPECIAL_VOID,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, special_factory,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/floors/special",
    description=(
        "Special substrates — Chasm, Pit, Abyss, Void — across "
        "rect / octagon / circle shape rows. Depth / parallax / "
        "dark-vignette effects per style; no decorator bit needed."
    ),
    columns=[
        ColumnSpec("Chasm", special_factory(style=SPECIAL_CHASM)),
        ColumnSpec("Pit", special_factory(style=SPECIAL_PIT)),
        ColumnSpec("Abyss", special_factory(style=SPECIAL_ABYSS)),
        ColumnSpec("Void", special_factory(style=SPECIAL_VOID)),
    ],
    seed=7,
    params={"family": "Special"},
))


__all__ = []

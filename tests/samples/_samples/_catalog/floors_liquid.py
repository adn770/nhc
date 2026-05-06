"""Liquid floor catalog page — 2 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import LIQUID_LAVA, LIQUID_WATER

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    liquid_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/floors/liquid",
    description=(
        "Liquid substrates — Water, Lava — across rect / octagon / "
        "circle shape rows. Static substrate fills; surface motion "
        "(Ripples / LavaCracks decorator bits) ride on the "
        "decorator-bits catalog page."
    ),
    columns=[
        ColumnSpec("Water", liquid_factory(style=LIQUID_WATER)),
        ColumnSpec("Lava", liquid_factory(style=LIQUID_LAVA)),
    ],
    seed=7,
    params={"family": "Liquid"},
))


__all__ = []

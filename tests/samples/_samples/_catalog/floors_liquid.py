"""Liquid floor catalog page — 2 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    LIQUID_ACID, LIQUID_BRACKISH, LIQUID_LAVA, LIQUID_SLIME,
    LIQUID_TAR, LIQUID_WATER,
)

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


register_catalog_page(CatalogPageSpec(
    name="styles-extra",
    category="synthetic/floors/liquid",
    description=(
        "Liquid post-Phase-5 substrates — Acid (caustic yellow-green), "
        "Slime (dark green ooze), Tar (viscous black with sheen "
        "highlight), Brackish (muddy estuary green-brown) — across "
        "rect / octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("Acid", liquid_factory(style=LIQUID_ACID)),
        ColumnSpec("Slime", liquid_factory(style=LIQUID_SLIME)),
        ColumnSpec("Tar", liquid_factory(style=LIQUID_TAR)),
        ColumnSpec("Brackish", liquid_factory(style=LIQUID_BRACKISH)),
    ],
    seed=7,
    params={"family": "Liquid", "axis": "styles-extra"},
))


__all__ = []

"""Decorator-bit catalog pages — 9 decorator bits split across
two pages of 4-5 columns each, sweeping rect / octagon / circle
shape rows.

- ``bits-1`` — GridLines, Cracks, Scratches, Moss (architectural
  + organic decay).
- ``bits-2`` — Blood, Ash, Puddles, Ripples, LavaCracks (substance
  spills + liquid surface motion).

Each cell pairs a base PaintOp (Plain) with a StampOp carrying the
column's decorator-bit mask. The Rust ``transform/png/stamp_op.rs``
walks the StampOp.region's tiles and emits the matching painter
for each set bit. Bit values mirror the Rust ``bit::`` constants.
"""

from __future__ import annotations

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, stamp_factory,
)


# Bit values mirror crates/nhc-render/src/transform/png/stamp_op.rs
# `pub mod bit { ... }`. Kept as locals so this module reads
# self-contained.
_BIT_GRID_LINES = 1 << 0
_BIT_CRACKS = 1 << 1
_BIT_SCRATCHES = 1 << 2
_BIT_RIPPLES = 1 << 3
_BIT_LAVA_CRACKS = 1 << 4
_BIT_MOSS = 1 << 5
_BIT_BLOOD = 1 << 6
_BIT_ASH = 1 << 7
_BIT_PUDDLES = 1 << 8


# ── Bits 1: architectural + organic decay ──────────────────────


register_catalog_page(CatalogPageSpec(
    name="bits-1",
    category="synthetic/decorators",
    description=(
        "Decorator bits set 1 — GridLines, Cracks, Scratches, Moss "
        "— stamped over a Plain base across rect / octagon / circle "
        "shape rows. Each cell carries a single bit; the StampOp "
        "walks the region tiles to drop per-tile stamps."
    ),
    columns=[
        ColumnSpec("GridLines", stamp_factory(decorator_mask=_BIT_GRID_LINES)),
        ColumnSpec("Cracks", stamp_factory(decorator_mask=_BIT_CRACKS)),
        ColumnSpec("Scratches", stamp_factory(decorator_mask=_BIT_SCRATCHES)),
        ColumnSpec("Moss", stamp_factory(decorator_mask=_BIT_MOSS)),
    ],
    seed=7,
    params={"axis": "decorator-bits-1"},
))


# ── Bits 2: substance spills + liquid surface motion ──────────


register_catalog_page(CatalogPageSpec(
    name="bits-2",
    category="synthetic/decorators",
    description=(
        "Decorator bits set 2 — Blood, Ash, Puddles, Ripples, "
        "LavaCracks — stamped over a Plain base across rect / "
        "octagon / circle shape rows. Ripples + LavaCracks are "
        "Liquid-substrate decorations; they render the static "
        "surface-motion patterns on top of any base substrate."
    ),
    columns=[
        ColumnSpec("Blood", stamp_factory(decorator_mask=_BIT_BLOOD)),
        ColumnSpec("Ash", stamp_factory(decorator_mask=_BIT_ASH)),
        ColumnSpec("Puddles", stamp_factory(decorator_mask=_BIT_PUDDLES)),
        ColumnSpec("Ripples", stamp_factory(decorator_mask=_BIT_RIPPLES)),
        ColumnSpec("LavaCracks", stamp_factory(
            decorator_mask=_BIT_LAVA_CRACKS,
        )),
    ],
    seed=7,
    params={"axis": "decorator-bits-2"},
))


__all__ = []

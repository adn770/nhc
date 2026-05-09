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
# Post-Phase-5 deferred-polish bits.
_BIT_FROST = 1 << 9
_BIT_MOLD = 1 << 10
_BIT_LEAVES = 1 << 11
_BIT_SNOW = 1 << 12
_BIT_SAND_DRIFT = 1 << 13
_BIT_POLLEN = 1 << 14
_BIT_STAINS = 1 << 15
_BIT_INSCRIPTIONS = 1 << 16
_BIT_FOOTPRINTS = 1 << 17


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


# ── Bits 3: weather + organic surface coatings ────────────────


register_catalog_page(CatalogPageSpec(
    name="bits-3",
    category="synthetic/decorators",
    description=(
        "Decorator bits set 3 — Frost (pale ice crystals at 30% "
        "density), Mold (dark green patches at 8%), Leaves (autumn "
        "leaf scatter at 20%), Snow (white drift dots at 40%) — "
        "stamped over a Plain base across rect / octagon / circle "
        "shape rows."
    ),
    columns=[
        ColumnSpec("Frost", stamp_factory(decorator_mask=_BIT_FROST)),
        ColumnSpec("Mold", stamp_factory(decorator_mask=_BIT_MOLD)),
        ColumnSpec("Leaves", stamp_factory(decorator_mask=_BIT_LEAVES)),
        ColumnSpec("Snow", stamp_factory(decorator_mask=_BIT_SNOW)),
    ],
    seed=7,
    params={"axis": "decorator-bits-3"},
))


# ── Bits 4: trace marks + airborne particulates ───────────────


register_catalog_page(CatalogPageSpec(
    name="bits-4",
    category="synthetic/decorators",
    description=(
        "Decorator bits set 4 — SandDrift (tan grains at 35% "
        "density), Pollen (yellow specks at 15%), Stains (large "
        "brown-black patches at 6%), Inscriptions (short engraved "
        "stroke marks at 4%), Footprints (boot-shape stamps at "
        "5%) — stamped over a Plain base across rect / octagon / "
        "circle shape rows."
    ),
    columns=[
        ColumnSpec("SandDrift", stamp_factory(decorator_mask=_BIT_SAND_DRIFT)),
        ColumnSpec("Pollen", stamp_factory(decorator_mask=_BIT_POLLEN)),
        ColumnSpec("Stains", stamp_factory(decorator_mask=_BIT_STAINS)),
        ColumnSpec("Inscriptions", stamp_factory(
            decorator_mask=_BIT_INSCRIPTIONS,
        )),
        ColumnSpec("Footprints", stamp_factory(
            decorator_mask=_BIT_FOOTPRINTS,
        )),
    ],
    seed=7,
    params={"axis": "decorator-bits-4"},
))


__all__ = []

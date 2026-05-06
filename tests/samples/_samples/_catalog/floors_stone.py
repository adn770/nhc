"""Stone floor catalog pages.

One catalog page per Stone style group:

- ``cobblestone`` — 4 sub-patterns (Herringbone, Stack, Rubble,
  Mosaic) × 3 shapes.
- ``brick`` — 3 bonds (RunningBond, EnglishBond, FlemishBond) × 3
  shapes.
- ``ashlar-and-singles-1`` — Ashlar (×2 sub-patterns) + Flagstone +
  OpusRomano = 4 cols × 3 shapes.
- ``singles-2`` — FieldStone, Pinwheel, Hopscotch, CrazyPaving = 4
  cols × 3 shapes.

Surfaces per-shape bleed at room corners + curves alongside the
sub-pattern divergence pinned by ``crates/nhc-render/src/painter/
families/stone.rs``'s test suite.
"""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    STONE_ASHLAR,
    STONE_BRICK,
    STONE_BRICK_ENGLISH_BOND,
    STONE_BRICK_FLEMISH_BOND,
    STONE_BRICK_RUNNING_BOND,
    STONE_COBBLE_HERRINGBONE,
    STONE_COBBLE_MOSAIC,
    STONE_COBBLE_RUBBLE,
    STONE_COBBLE_STACK,
    STONE_COBBLESTONE,
    STONE_CRAZY_PAVING,
    STONE_FIELDSTONE,
    STONE_FLAGSTONE,
    STONE_HOPSCOTCH,
    STONE_OPUS_ROMANO,
    STONE_PINWHEEL,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, stone_factory,
)


# ── Cobblestone (4 sub-patterns × 3 shapes) ──────────────────────


register_catalog_page(CatalogPageSpec(
    name="cobblestone",
    category="synthetic/floors/stone",
    description=(
        "Stone Cobblestone — four sub-pattern layouts (Herringbone, "
        "Stack, Rubble, Mosaic) swept across rect / octagon / circle "
        "shape rows. Surfaces per-shape bleed at corners + curves."
    ),
    columns=[
        ColumnSpec("Herringbone", stone_factory(
            style=STONE_COBBLESTONE, sub_pattern=STONE_COBBLE_HERRINGBONE,
        )),
        ColumnSpec("Stack", stone_factory(
            style=STONE_COBBLESTONE, sub_pattern=STONE_COBBLE_STACK,
        )),
        ColumnSpec("Rubble", stone_factory(
            style=STONE_COBBLESTONE, sub_pattern=STONE_COBBLE_RUBBLE,
        )),
        ColumnSpec("Mosaic", stone_factory(
            style=STONE_COBBLESTONE, sub_pattern=STONE_COBBLE_MOSAIC,
        )),
    ],
    seed=7,
    params={"family": "Stone", "style": "Cobblestone"},
))


# ── Brick (3 bonds × 3 shapes) ───────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="brick",
    category="synthetic/floors/stone",
    description=(
        "Stone Brick — three bond patterns (RunningBond, EnglishBond, "
        "FlemishBond) swept across rect / octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("RunningBond", stone_factory(
            style=STONE_BRICK, sub_pattern=STONE_BRICK_RUNNING_BOND,
        )),
        ColumnSpec("EnglishBond", stone_factory(
            style=STONE_BRICK, sub_pattern=STONE_BRICK_ENGLISH_BOND,
        )),
        ColumnSpec("FlemishBond", stone_factory(
            style=STONE_BRICK, sub_pattern=STONE_BRICK_FLEMISH_BOND,
        )),
    ],
    seed=7,
    params={"family": "Stone", "style": "Brick"},
))


# ── Ashlar (× 2 sub-patterns) + Flagstone + OpusRomano ──────────


register_catalog_page(CatalogPageSpec(
    name="ashlar-and-singles-1",
    category="synthetic/floors/stone",
    description=(
        "Stone Ashlar (EvenJoint, StaggeredJoint) + Flagstone + "
        "OpusRomano. Mixed sub-pattern + single-layout styles "
        "across rect / octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("Ashlar Even", stone_factory(
            style=STONE_ASHLAR, sub_pattern=0,
        )),
        ColumnSpec("Ashlar Staggered", stone_factory(
            style=STONE_ASHLAR, sub_pattern=1,
        )),
        ColumnSpec("Flagstone", stone_factory(style=STONE_FLAGSTONE)),
        ColumnSpec("OpusRomano", stone_factory(style=STONE_OPUS_ROMANO)),
    ],
    seed=7,
    params={"family": "Stone"},
))


# ── FieldStone, Pinwheel, Hopscotch, CrazyPaving ────────────────


register_catalog_page(CatalogPageSpec(
    name="singles-2",
    category="synthetic/floors/stone",
    description=(
        "Stone single-layout styles: FieldStone, Pinwheel, Hopscotch, "
        "CrazyPaving. Four no-sub-pattern styles across rect / "
        "octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("FieldStone", stone_factory(style=STONE_FIELDSTONE)),
        ColumnSpec("Pinwheel", stone_factory(style=STONE_PINWHEEL)),
        ColumnSpec("Hopscotch", stone_factory(style=STONE_HOPSCOTCH)),
        ColumnSpec("CrazyPaving", stone_factory(style=STONE_CRAZY_PAVING)),
    ],
    seed=7,
    params={"family": "Stone"},
))


__all__ = []

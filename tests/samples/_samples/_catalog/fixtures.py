"""Fixture catalog pages — 12 FixtureKind variants split into
three pages of 4 columns each, sweeping rect / octagon / circle
shape rows.

- ``creature-scale`` — small per-tile stamps (Web, Skull, Bone,
  LooseStone) typically scattered as room dressing.
- ``objects-1`` — large objects (Well, Fountain, Tree, Bush)
  occupying central tile.
- ``objects-2`` — narrative objects (Stair, Mushroom, Gravestone,
  Sign) occupying central tile.
"""

from __future__ import annotations

from nhc.rendering.ir._fb.FixtureKind import FixtureKind

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    fixture_factory, register_catalog_page,
)


# ── Creature-scale fixtures ─────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="creature-scale",
    category="synthetic/fixtures",
    description=(
        "Creature-scale fixtures — Web, Skull, Bone, LooseStone — "
        "stamped at the centre tile of each cell. Per-anchor RNG "
        "drives sub-style variation (e.g. Web corner, Bone count)."
    ),
    columns=[
        ColumnSpec("Web", fixture_factory(kind=FixtureKind.Web)),
        ColumnSpec("Skull", fixture_factory(kind=FixtureKind.Skull)),
        ColumnSpec("Bone", fixture_factory(kind=FixtureKind.Bone)),
        ColumnSpec("LooseStone", fixture_factory(
            kind=FixtureKind.LooseStone,
        )),
    ],
    seed=7,
    params={"axis": "creature-scale"},
))


# ── Object fixtures (set 1) ─────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="objects-1",
    category="synthetic/fixtures",
    description=(
        "Object fixtures — Well, Fountain, Tree, Bush — stamped at "
        "the centre tile of each cell. Wells / fountains carry "
        "shape variants via Anchor.variant; trees + bushes lift "
        "their canopies from the v4 primitives."
    ),
    columns=[
        ColumnSpec("Well", fixture_factory(kind=FixtureKind.Well)),
        ColumnSpec("Fountain", fixture_factory(kind=FixtureKind.Fountain)),
        ColumnSpec("Tree", fixture_factory(kind=FixtureKind.Tree)),
        ColumnSpec("Bush", fixture_factory(kind=FixtureKind.Bush)),
    ],
    seed=7,
    params={"axis": "objects-1"},
))


# ── Object fixtures (set 2) ─────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="objects-2",
    category="synthetic/fixtures",
    description=(
        "Narrative fixtures — Stair, Mushroom, Gravestone, Sign — "
        "stamped at the centre tile of each cell. Each kind has "
        "1-3 variants visible via Anchor.variant; this page pins "
        "variant=0 for clarity."
    ),
    columns=[
        ColumnSpec("Stair", fixture_factory(kind=FixtureKind.Stair)),
        ColumnSpec("Mushroom", fixture_factory(kind=FixtureKind.Mushroom)),
        ColumnSpec("Gravestone", fixture_factory(
            kind=FixtureKind.Gravestone,
        )),
        ColumnSpec("Sign", fixture_factory(kind=FixtureKind.Sign)),
    ],
    seed=7,
    params={"axis": "objects-2"},
))


__all__ = []

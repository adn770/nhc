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


# ── Post-Phase-5 deferred-polish FixtureKind additions ────────


register_catalog_page(CatalogPageSpec(
    name="containers",
    category="synthetic/fixtures",
    description=(
        "Container fixtures — Chest (wooden coffer + iron bands + "
        "brass lock), Crate (square with cross-bracing), Barrel "
        "(vertical oval body + 3 hoops). Plus Trough (long water "
        "trough; variant=1 swaps to feed)."
    ),
    columns=[
        ColumnSpec("Chest", fixture_factory(kind=FixtureKind.Chest)),
        ColumnSpec("Crate", fixture_factory(kind=FixtureKind.Crate)),
        ColumnSpec("Barrel", fixture_factory(kind=FixtureKind.Barrel)),
        ColumnSpec("Trough", fixture_factory(kind=FixtureKind.Trough)),
    ],
    seed=7,
    params={"axis": "containers"},
))


register_catalog_page(CatalogPageSpec(
    name="ritual",
    category="synthetic/fixtures",
    description=(
        "Ritual / ceremonial fixtures — Altar (stone slab + "
        "raised top), Brazier (footed bowl + flame), Statue "
        "(humanoid silhouette on a base), ChalkCircle (pale "
        "arcane summoning ring with radial inscriptions)."
    ),
    columns=[
        ColumnSpec("Altar", fixture_factory(kind=FixtureKind.Altar)),
        ColumnSpec("Brazier", fixture_factory(kind=FixtureKind.Brazier)),
        ColumnSpec("Statue", fixture_factory(kind=FixtureKind.Statue)),
        ColumnSpec("ChalkCircle", fixture_factory(
            kind=FixtureKind.ChalkCircle,
        )),
    ],
    seed=7,
    params={"axis": "ritual"},
))


register_catalog_page(CatalogPageSpec(
    name="architecture",
    category="synthetic/fixtures",
    description=(
        "Architectural fixtures — Pillar (round column + base/cap), "
        "Pedestal (short circular plinth), Ladder (vertical rails "
        "+ rungs), Trapdoor (square plank + diagonal brace + "
        "hinge), plus Footprint (boot-shape stamp distinct from "
        "the per-tile-decorator Footprints bit)."
    ),
    columns=[
        ColumnSpec("Pillar", fixture_factory(kind=FixtureKind.Pillar)),
        ColumnSpec("Pedestal", fixture_factory(kind=FixtureKind.Pedestal)),
        ColumnSpec("Ladder", fixture_factory(kind=FixtureKind.Ladder)),
        ColumnSpec("Trapdoor", fixture_factory(kind=FixtureKind.Trapdoor)),
        ColumnSpec("Footprint", fixture_factory(
            kind=FixtureKind.Footprint,
        )),
    ],
    seed=7,
    params={"axis": "architecture"},
))


# ── Farm-animal fixtures ────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="farm-animals-1",
    category="synthetic/fixtures",
    description=(
        "Farm animals set 1 — Cow (brown body + hide patches + "
        "dark head), Sheep (round white-fleece body + dark face), "
        "Pig (pink oval body + snout + curly tail). Top-down "
        "silhouettes; body extends along +x axis."
    ),
    columns=[
        ColumnSpec("Cow", fixture_factory(kind=FixtureKind.Cow)),
        ColumnSpec("Sheep", fixture_factory(kind=FixtureKind.Sheep)),
        ColumnSpec("Pig", fixture_factory(kind=FixtureKind.Pig)),
    ],
    seed=7,
    params={"axis": "farm-animals-1"},
))


register_catalog_page(CatalogPageSpec(
    name="farm-animals-2",
    category="synthetic/fixtures",
    description=(
        "Farm animals set 2 — Chicken (small buff body + red comb "
        "+ orange beak), Goat (gray-brown body + horns + beard), "
        "Horse (long body + dark mane stripe + tail). Top-down "
        "silhouettes; body extends along +x axis."
    ),
    columns=[
        ColumnSpec("Chicken", fixture_factory(kind=FixtureKind.Chicken)),
        ColumnSpec("Goat", fixture_factory(kind=FixtureKind.Goat)),
        ColumnSpec("Horse", fixture_factory(kind=FixtureKind.Horse)),
    ],
    seed=7,
    params={"axis": "farm-animals-2"},
))


# ── Farm-structure fixtures ─────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="farm-structures",
    category="synthetic/fixtures",
    description=(
        "Static farm structures — Hayrick (round haystack with "
        "concentric peaked-top rings), Beehive (straw skep + "
        "concentric ring outlines), Scarecrow (cross silhouette "
        "+ straw hat), Plough (pointed metal blade + 2 trailing "
        "wooden handles). Top-down silhouettes; +x is the "
        "implement's working direction (matches the farm-animal "
        "head-at-+x convention)."
    ),
    columns=[
        ColumnSpec("Hayrick", fixture_factory(kind=FixtureKind.Hayrick)),
        ColumnSpec("Beehive", fixture_factory(kind=FixtureKind.Beehive)),
        ColumnSpec("Scarecrow", fixture_factory(
            kind=FixtureKind.Scarecrow,
        )),
        ColumnSpec("Plough", fixture_factory(kind=FixtureKind.Plough)),
    ],
    seed=7,
    params={"axis": "farm-structures"},
))


__all__ = []

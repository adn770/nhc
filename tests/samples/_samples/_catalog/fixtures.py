"""Fixture catalog pages — FixtureKind variants grouped by axis.

- ``creature-scale`` — small per-tile stamps (Web, Skull, Bone,
  LooseStone) typically scattered as room dressing.
- ``objects-1`` — wells + fountains, all 7 variants in a single
  page (2 well + 5 fountain shapes across two rows).
- ``objects-2`` — narrative objects (Stair, Mushroom, Gravestone,
  Sign) occupying central tile.
- ``vegetation`` — Tree + Bush.
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
    rows=("",),
    cell_shape="rect",
    params={"axis": "creature-scale"},
))


# ── Object fixtures (set 1) ─────────────────────────────────────


# Well + Fountain share a "shape" axis on Anchor.variant — Well
# implements variants 0 (Circle) and 1 (Square); Fountain extends
# that to 2 (Circle 3×3), 3 (Square 3×3), and 4 (Cross). The page
# lays variants 0..4 along the column axis with Well in the top
# row + Fountain in the bottom row, so the column header reads
# as the *shape* and each row reads as the *fixture kind*.
# Cells where the fixture kind has no matching variant (Well
# rows 2..4) render a blank Plain rect by intent — the gap makes
# Well's smaller variant set visible at a glance.


# Fountain primitives interpret ``Anchor.x, y`` as the *top-left*
# tile of a multi-tile footprint, so a centred placement needs a
# tile_offset that puts the footprint's centre at the cell's
# centre. Variants 0/1 are 2×2; 2/3/4 are 3×3 (Cross too). With
# a 4-tile catalog cell the 2×2 anchor lands one tile up-left of
# cell_center_tile; the 3×3 anchor lands one tile up-left and
# accepts a half-tile right-bias (integer-tile arithmetic can't
# perfectly centre an odd-side footprint in an even-side cell).
_FOUNTAIN_TILE_OFFSETS: dict[int, tuple[int, int]] = {
    0: (-1, -1),  # circle 2×2 — perfectly centred
    1: (-1, -1),  # square 2×2 — perfectly centred
    2: (-1, -1),  # circle 3×3 — half-tile right-bias
    3: (-1, -1),  # square 3×3 — half-tile right-bias
    4: (-1, -1),  # cross — half-tile right-bias
}


def _well_or_fountain_factory(variant: int):
    """Row 0 → Well (only variants 0-1 valid; higher variants
    render a blank Plain rect). Row 1 → Fountain (all 5 valid)."""
    fountain = fixture_factory(
        kind=FixtureKind.Fountain, variant=variant,
        tile_offset=_FOUNTAIN_TILE_OFFSETS[variant],
    )
    if variant < 2:
        well = fixture_factory(
            kind=FixtureKind.Well, variant=variant,
        )
    else:
        # Sentinel — empty cell. The page builder still
        # populates the cell's Region; returning an empty op
        # list leaves the canvas parchment-coloured under the
        # cell, so the absence reads as a deliberate gap.
        well = None

    def factory(region_id, page_seed, col_idx, row_idx):
        if row_idx == 0:
            if well is None:
                return []
            return well(region_id, page_seed, col_idx, row_idx)
        return fountain(region_id, page_seed, col_idx, row_idx)

    return factory


register_catalog_page(CatalogPageSpec(
    name="objects-1",
    category="synthetic/fixtures",
    description=(
        "Wells + Fountains — every Anchor.variant the Rust "
        "primitives implement. Well has 2 variants (Circle, "
        "Square) shown in the top row; Fountain has 5 variants "
        "(Circle 2×2, Square 2×2, Circle 3×3, Square 3×3, Cross) "
        "in the bottom row. Columns 2-4 on the Well row stay "
        "intentionally blank — Well doesn't host the wider "
        "shapes."
    ),
    columns=[
        ColumnSpec("Circle 2×2", _well_or_fountain_factory(0)),
        ColumnSpec("Square 2×2", _well_or_fountain_factory(1)),
        ColumnSpec("Circle 3×3", _well_or_fountain_factory(2)),
        ColumnSpec("Square 3×3", _well_or_fountain_factory(3)),
        ColumnSpec("Cross", _well_or_fountain_factory(4)),
    ],
    seed=7,
    rows=("Well", "Fountain"),
    cell_shape="rect",
    params={"axis": "wells-fountains"},
))


register_catalog_page(CatalogPageSpec(
    name="vegetation",
    category="synthetic/fixtures",
    description=(
        "Vegetation fixtures — Tree (broadleaf canopy + trunk) "
        "and Bush (low foliage clump). Stamped at the centre "
        "tile of each cell."
    ),
    columns=[
        ColumnSpec("Tree", fixture_factory(kind=FixtureKind.Tree)),
        ColumnSpec("Bush", fixture_factory(kind=FixtureKind.Bush)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "vegetation"},
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
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
    rows=("",),
    cell_shape="rect",
    params={"axis": "farm-structures"},
))


# ── Dwelling interior fixtures ─────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="dwelling-interior-1",
    category="synthetic/fixtures",
    description=(
        "Dwelling interior set 1 — Table (rectangular dining "
        "table along +x; variant=1 swaps to round), Chair (small "
        "seat + back-rest on the -y edge), Bed (frame + mattress "
        "+ pillow at +x head end). Top-down silhouettes."
    ),
    columns=[
        ColumnSpec("Table", fixture_factory(kind=FixtureKind.Table)),
        ColumnSpec("Chair", fixture_factory(kind=FixtureKind.Chair)),
        ColumnSpec("Bed", fixture_factory(kind=FixtureKind.Bed)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "dwelling-interior-1"},
))


register_catalog_page(CatalogPageSpec(
    name="dwelling-interior-2",
    category="synthetic/fixtures",
    description=(
        "Dwelling interior set 2 — Bookshelf (frame + 8 vertical "
        "book-spine stripes cycling 4 hues), Hearth (stone "
        "fireplace + dark interior + flame; variant=1 paints a "
        "cold hearth), Cauldron (round black pot + dark rim + "
        "bright green bubble; variant=1 omits the bubble)."
    ),
    columns=[
        ColumnSpec("Bookshelf", fixture_factory(kind=FixtureKind.Bookshelf)),
        ColumnSpec("Hearth", fixture_factory(kind=FixtureKind.Hearth)),
        ColumnSpec("Cauldron", fixture_factory(kind=FixtureKind.Cauldron)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "dwelling-interior-2"},
))


# ── Outdoor camp fixtures ──────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="outdoor-camp-1",
    category="synthetic/fixtures",
    description=(
        "Outdoor camp set 1 — Campfire (stone ring + ash + flame; "
        "variant=1 paints a cold campfire), Tent (triangular "
        "canvas pointing +x with ridge stripe + door slit), Logs "
        "(3-log triangular pile of cross-section ends with bark "
        "+ wood + core rings)."
    ),
    columns=[
        ColumnSpec("Campfire", fixture_factory(kind=FixtureKind.Campfire)),
        ColumnSpec("Tent", fixture_factory(kind=FixtureKind.Tent)),
        ColumnSpec("Logs", fixture_factory(kind=FixtureKind.Logs)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "outdoor-camp-1"},
))


register_catalog_page(CatalogPageSpec(
    name="outdoor-camp-2",
    category="synthetic/fixtures",
    description=(
        "Outdoor camp set 2 — Stump (tree-stump cross-section "
        "with bark + wood + 2 growth rings; variant=1 adds 4 "
        "root flares), Boulder (rounded gray stone with -y "
        "highlight + +y shadow; variant=1 renders a smaller "
        "boulder)."
    ),
    columns=[
        ColumnSpec("Stump", fixture_factory(kind=FixtureKind.Stump)),
        ColumnSpec("Boulder", fixture_factory(kind=FixtureKind.Boulder)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "outdoor-camp-2"},
))


__all__ = []

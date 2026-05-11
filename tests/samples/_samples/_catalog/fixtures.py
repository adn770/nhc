"""Fixture catalog pages — FixtureKind variants grouped by axis.

Single-tile fixtures use ``small_fixture_factory`` which renders
each cell twice: a natural-size preview anchored at the cell's
top-left tile and a zoomed (3×) copy filling the remaining 3×3
area. Multi-tile fixtures (Wells + Fountains) use the standard
``fixture_factory`` with a ``tile_offset`` instead.

- ``creature-scale`` — small per-tile stamps (Web, Skull, Bone,
  LooseStone) typically scattered as room dressing.
- ``objects-1`` — Wells + Fountains, all 7 variants in a single
  page (2 well + 5 fountain shapes across two rows).
- ``vegetation`` — Tree + Bush.
- ``objects-2`` — narrative objects (Stair, Mushroom,
  Gravestone, Sign).
- ``containers`` — Chest, Crate, Barrel, Trough.
- ``ritual`` — Altar, Brazier, Statue, ChalkCircle.
- ``architecture`` — Pillar, Pedestal, Ladder, Trapdoor,
  Footprint.
- ``farm-animals`` — Cow / Sheep / Pig / Chicken / Goat / Horse
  (post-merge of farm-animals-1 + farm-animals-2).
- ``farm-structures`` — Hayrick, Beehive, Scarecrow, Plough.
- ``dwelling-interior`` — Table / Chair / Bed / Bookshelf /
  Hearth / Cauldron (post-merge of dwelling-interior-1 + 2).
- ``outdoor-camp`` — Campfire / Tent / Logs / Stump / Boulder
  (post-merge of outdoor-camp-1 + 2).
"""

from __future__ import annotations

from nhc.rendering.ir._fb.FixtureKind import FixtureKind

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    fixture_factory, register_catalog_page, small_fixture_factory,
)


# ── Creature-scale fixtures ─────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="creature-scale",
    category="synthetic/fixtures",
    description=(
        "Creature-scale fixtures — Web, Skull, Bone, LooseStone — "
        "rendered twice per cell: natural-size preview in the "
        "top-left tile + 3× zoom filling the remaining area."
    ),
    columns=[
        ColumnSpec("Web", small_fixture_factory(kind=FixtureKind.Web)),
        ColumnSpec("Skull", small_fixture_factory(kind=FixtureKind.Skull)),
        ColumnSpec("Bone", small_fixture_factory(kind=FixtureKind.Bone)),
        ColumnSpec("LooseStone", small_fixture_factory(
            kind=FixtureKind.LooseStone,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "creature-scale"},
))


# ── Wells + Fountains ───────────────────────────────────────────

# Well + Fountain share a "shape" axis on Anchor.variant — Well
# implements variants 0 (Circle) and 1 (Square); Fountain extends
# that to 2 (Circle 3×3), 3 (Square 3×3), and 4 (Cross). The page
# lays variants 0..4 along the column axis with Well in the top
# row + Fountain in the bottom row, so the column header reads
# as the *shape* and each row reads as the *fixture kind*.

# Fountain primitives interpret ``Anchor.x, y`` as the *top-left*
# tile of a multi-tile footprint, so a centred placement needs a
# tile_offset that puts the footprint's centre at the cell's
# centre. All five variants use offset (-1, -1) for placement in
# a 4-tile catalog cell.
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


# ── Vegetation ─────────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="vegetation",
    category="synthetic/fixtures",
    description=(
        "Vegetation fixtures — Tree (broadleaf canopy + trunk) "
        "and Bush (low foliage clump). Rendered twice per cell: "
        "natural-size preview in the top-left tile + 3× zoom in "
        "the remaining area."
    ),
    columns=[
        ColumnSpec("Tree", small_fixture_factory(kind=FixtureKind.Tree)),
        ColumnSpec("Bush", small_fixture_factory(kind=FixtureKind.Bush)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "vegetation"},
))


# ── Narrative objects ──────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="objects-2",
    category="synthetic/fixtures",
    description=(
        "Narrative fixtures — Stair, Mushroom, Gravestone, Sign. "
        "Rendered twice per cell: natural-size preview in the "
        "top-left tile + 3× zoom in the remaining area."
    ),
    columns=[
        ColumnSpec("Stair", small_fixture_factory(kind=FixtureKind.Stair)),
        ColumnSpec("Mushroom", small_fixture_factory(
            kind=FixtureKind.Mushroom,
        )),
        ColumnSpec("Gravestone", small_fixture_factory(
            kind=FixtureKind.Gravestone,
        )),
        ColumnSpec("Sign", small_fixture_factory(kind=FixtureKind.Sign)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "objects-2"},
))


# ── Containers ─────────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="containers",
    category="synthetic/fixtures",
    description=(
        "Container fixtures — Chest (wooden coffer + iron bands + "
        "brass lock), Crate (square with cross-bracing), Barrel "
        "(vertical oval body + 3 hoops), Trough (long water "
        "trough; variant=1 swaps to feed). Rendered twice per "
        "cell: natural-size preview + 3× zoom."
    ),
    columns=[
        ColumnSpec("Chest", small_fixture_factory(kind=FixtureKind.Chest)),
        ColumnSpec("Crate", small_fixture_factory(kind=FixtureKind.Crate)),
        ColumnSpec("Barrel", small_fixture_factory(kind=FixtureKind.Barrel)),
        ColumnSpec("Trough", small_fixture_factory(kind=FixtureKind.Trough)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "containers"},
))


# ── Ritual ─────────────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="ritual",
    category="synthetic/fixtures",
    description=(
        "Ritual / ceremonial fixtures — Altar (stone slab + "
        "raised top), Brazier (footed bowl + flame), Statue "
        "(humanoid silhouette on a base), ChalkCircle (pale "
        "arcane summoning ring with radial inscriptions). "
        "Rendered twice per cell: natural-size preview + 3× zoom."
    ),
    columns=[
        ColumnSpec("Altar", small_fixture_factory(kind=FixtureKind.Altar)),
        ColumnSpec("Brazier", small_fixture_factory(
            kind=FixtureKind.Brazier,
        )),
        ColumnSpec("Statue", small_fixture_factory(
            kind=FixtureKind.Statue,
        )),
        ColumnSpec("ChalkCircle", small_fixture_factory(
            kind=FixtureKind.ChalkCircle,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "ritual"},
))


# ── Architecture ───────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="architecture",
    category="synthetic/fixtures",
    description=(
        "Architectural fixtures — Pillar (round column + base/cap), "
        "Pedestal (short circular plinth), Ladder (vertical rails "
        "+ rungs), Trapdoor (square plank + diagonal brace + "
        "hinge), Footprint (boot-shape stamp distinct from "
        "the per-tile-decorator Footprints bit). Rendered twice "
        "per cell: natural-size preview + 3× zoom."
    ),
    columns=[
        ColumnSpec("Pillar", small_fixture_factory(
            kind=FixtureKind.Pillar,
        )),
        ColumnSpec("Pedestal", small_fixture_factory(
            kind=FixtureKind.Pedestal,
        )),
        ColumnSpec("Ladder", small_fixture_factory(
            kind=FixtureKind.Ladder,
        )),
        ColumnSpec("Trapdoor", small_fixture_factory(
            kind=FixtureKind.Trapdoor,
        )),
        ColumnSpec("Footprint", small_fixture_factory(
            kind=FixtureKind.Footprint,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "architecture"},
))


# ── Farm animals (merged 1 + 2) ────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="farm-animals",
    category="synthetic/fixtures",
    description=(
        "Farm animals — Cow / Sheep / Pig / Chicken / Goat / "
        "Horse. Top-down silhouettes; body extends along +x axis. "
        "Rendered twice per cell: natural-size preview in the "
        "top-left tile + 3× zoom in the remaining area."
    ),
    columns=[
        ColumnSpec("Cow", small_fixture_factory(kind=FixtureKind.Cow)),
        ColumnSpec("Sheep", small_fixture_factory(kind=FixtureKind.Sheep)),
        ColumnSpec("Pig", small_fixture_factory(kind=FixtureKind.Pig)),
        ColumnSpec("Chicken", small_fixture_factory(
            kind=FixtureKind.Chicken,
        )),
        ColumnSpec("Goat", small_fixture_factory(kind=FixtureKind.Goat)),
        ColumnSpec("Horse", small_fixture_factory(kind=FixtureKind.Horse)),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "farm-animals"},
))


# ── Farm structures ────────────────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="farm-structures",
    category="synthetic/fixtures",
    description=(
        "Static farm structures — Hayrick (round haystack with "
        "concentric peaked-top rings), Beehive (straw skep + "
        "concentric ring outlines), Scarecrow (cross silhouette "
        "+ straw hat), Plough (pointed metal blade + 2 trailing "
        "wooden handles). Rendered twice per cell: natural-size "
        "preview + 3× zoom."
    ),
    columns=[
        ColumnSpec("Hayrick", small_fixture_factory(
            kind=FixtureKind.Hayrick,
        )),
        ColumnSpec("Beehive", small_fixture_factory(
            kind=FixtureKind.Beehive,
        )),
        ColumnSpec("Scarecrow", small_fixture_factory(
            kind=FixtureKind.Scarecrow,
        )),
        ColumnSpec("Plough", small_fixture_factory(
            kind=FixtureKind.Plough,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "farm-structures"},
))


# ── Dwelling interior (merged 1 + 2) ───────────────────────────


register_catalog_page(CatalogPageSpec(
    name="dwelling-interior",
    category="synthetic/fixtures",
    description=(
        "Dwelling interior fixtures — Table (variant=1 swaps to "
        "round), Chair (back-rest on the -y edge), Bed (frame + "
        "mattress + pillow at +x head end), Bookshelf (frame + 8 "
        "vertical book-spine stripes), Hearth (stone fireplace + "
        "interior + flame; variant=1 cold), Cauldron (round pot "
        "+ bubble; variant=1 omits the bubble). Rendered twice "
        "per cell."
    ),
    columns=[
        ColumnSpec("Table", small_fixture_factory(kind=FixtureKind.Table)),
        ColumnSpec("Chair", small_fixture_factory(kind=FixtureKind.Chair)),
        ColumnSpec("Bed", small_fixture_factory(kind=FixtureKind.Bed)),
        ColumnSpec("Bookshelf", small_fixture_factory(
            kind=FixtureKind.Bookshelf,
        )),
        ColumnSpec("Hearth", small_fixture_factory(
            kind=FixtureKind.Hearth,
        )),
        ColumnSpec("Cauldron", small_fixture_factory(
            kind=FixtureKind.Cauldron,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "dwelling-interior"},
))


# ── Outdoor camp (merged 1 + 2) ────────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="outdoor-camp",
    category="synthetic/fixtures",
    description=(
        "Outdoor camp fixtures — Campfire (stone ring + flame; "
        "variant=1 cold), Tent (triangular canvas pointing +x), "
        "Logs (3-log triangular pile), Stump (cross-section "
        "rings; variant=1 adds 4 root flares), Boulder (rounded "
        "stone; variant=1 smaller). Rendered twice per cell."
    ),
    columns=[
        ColumnSpec("Campfire", small_fixture_factory(
            kind=FixtureKind.Campfire,
        )),
        ColumnSpec("Tent", small_fixture_factory(kind=FixtureKind.Tent)),
        ColumnSpec("Logs", small_fixture_factory(kind=FixtureKind.Logs)),
        ColumnSpec("Stump", small_fixture_factory(kind=FixtureKind.Stump)),
        ColumnSpec("Boulder", small_fixture_factory(
            kind=FixtureKind.Boulder,
        )),
    ],
    seed=7,
    rows=("",),
    cell_shape="rect",
    params={"axis": "outdoor-camp"},
))


__all__ = []

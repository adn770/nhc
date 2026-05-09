"""Wood floor catalog pages.

Wood floors carry three axes (5 species × 4 layouts × 4 tones =
80 combos). Catalog enumeration breaks them up:

- ``overview`` — 6 representative (species, layout) at Medium tone.
- ``<species>-layouts`` — one page per species, 4 layouts at Medium.
- ``oak-tones`` — Oak × 4 tones × 1 layout (Plank).

Each page swept across rect / octagon / circle shape rows.
"""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    WOOD_AGED, WOOD_ASH, WOOD_BAMBOO, WOOD_BASKETWEAVE,
    WOOD_BIRCH, WOOD_BLEACHED, WOOD_BRICK, WOOD_CHARRED,
    WOOD_CHERRY, WOOD_CHEVRON, WOOD_DARK, WOOD_EBONY,
    WOOD_HERRINGBONE, WOOD_LIGHT, WOOD_MAHOGANY, WOOD_MAPLE,
    WOOD_MEDIUM, WOOD_OAK, WOOD_PARQUET, WOOD_PINE,
    WOOD_PLANK, WOOD_TEAK, WOOD_WALNUT, WOOD_WEATHERED,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    register_catalog_page, wood_factory,
)


_SPECIES_LABELS = {
    WOOD_OAK: "Oak",
    WOOD_WALNUT: "Walnut",
    WOOD_CHERRY: "Cherry",
    WOOD_PINE: "Pine",
    WOOD_WEATHERED: "Weathered",
}

_LAYOUT_LABELS = {
    WOOD_PLANK: "Plank",
    WOOD_BASKETWEAVE: "Basket",
    WOOD_PARQUET: "Parquet",
    WOOD_HERRINGBONE: "Herringbone",
}

_TONE_LABELS = {
    WOOD_LIGHT: "Light",
    WOOD_MEDIUM: "Medium",
    WOOD_DARK: "Dark",
    WOOD_CHARRED: "Charred",
}


# ── Wood overview (6 curated combos at Medium tone) ──────────────


register_catalog_page(CatalogPageSpec(
    name="overview",
    category="synthetic/floors/wood",
    description=(
        "Wood overview — six representative (species, layout) pairs "
        "at Medium tone, swept across rect / octagon / circle "
        "shape rows. Quick visual sanity check across the family."
    ),
    columns=[
        ColumnSpec("Oak Plank", wood_factory(
            species=WOOD_OAK, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Walnut Basket", wood_factory(
            species=WOOD_WALNUT, layout=WOOD_BASKETWEAVE, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Cherry Parquet", wood_factory(
            species=WOOD_CHERRY, layout=WOOD_PARQUET, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Pine Herring", wood_factory(
            species=WOOD_PINE, layout=WOOD_HERRINGBONE, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Weathered Plank", wood_factory(
            species=WOOD_WEATHERED, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Oak Parquet", wood_factory(
            species=WOOD_OAK, layout=WOOD_PARQUET, tone=WOOD_MEDIUM,
        )),
    ],
    seed=7,
    params={"family": "Wood"},
))


# ── Per-species layout pages ──────────────────────────────────


def _species_layouts_page(species: int) -> CatalogPageSpec:
    species_label = _SPECIES_LABELS[species]
    return CatalogPageSpec(
        name=f"{species_label.lower()}-layouts",
        category="synthetic/floors/wood",
        description=(
            f"Wood {species_label} — four layouts (Plank, Basket, "
            f"Parquet, Herringbone) at Medium tone across rect / "
            f"octagon / circle shape rows."
        ),
        columns=[
            ColumnSpec(_LAYOUT_LABELS[layout], wood_factory(
                species=species, layout=layout, tone=WOOD_MEDIUM,
            ))
            for layout in (
                WOOD_PLANK, WOOD_BASKETWEAVE,
                WOOD_PARQUET, WOOD_HERRINGBONE,
            )
        ],
        seed=7,
        params={"family": "Wood", "species": species_label},
    )


for _species in (
    WOOD_OAK, WOOD_WALNUT, WOOD_CHERRY, WOOD_PINE, WOOD_WEATHERED,
):
    register_catalog_page(_species_layouts_page(_species))


# ── Oak tones page (4 tones × Plank) ─────────────────────────────


register_catalog_page(CatalogPageSpec(
    name="oak-tones",
    category="synthetic/floors/wood",
    description=(
        "Wood Oak — four tones (Light, Medium, Dark, Charred) at "
        "Plank layout across rect / octagon / circle shape rows. "
        "Pins the tone darkening progression."
    ),
    columns=[
        ColumnSpec(_TONE_LABELS[tone], wood_factory(
            species=WOOD_OAK, layout=WOOD_PLANK, tone=tone,
        ))
        for tone in (
            WOOD_LIGHT, WOOD_MEDIUM, WOOD_DARK, WOOD_CHARRED,
        )
    ],
    seed=7,
    params={"family": "Wood", "species": "Oak", "axis": "tones"},
))


# ── Post-Phase-5 deferred-polish additions ──────────────────────


register_catalog_page(CatalogPageSpec(
    name="oak-layouts-extra",
    category="synthetic/floors/wood",
    description=(
        "Wood Oak — two post-Phase-5 layouts (Chevron, plank V's "
        "stacked vertically; Brick, half-stagger wood-block bond) "
        "at Medium tone across rect / octagon / circle shape rows. "
        "Pairs with the existing oak-layouts page."
    ),
    columns=[
        ColumnSpec("Chevron", wood_factory(
            species=WOOD_OAK, layout=WOOD_CHEVRON, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Brick", wood_factory(
            species=WOOD_OAK, layout=WOOD_BRICK, tone=WOOD_MEDIUM,
        )),
    ],
    seed=7,
    params={"family": "Wood", "species": "Oak", "axis": "layouts-extra"},
))


register_catalog_page(CatalogPageSpec(
    name="species-extra-1",
    category="synthetic/floors/wood",
    description=(
        "Wood new species set 1 — Mahogany (deep red-brown), Ebony "
        "(near-black), Ash (pale creamy), Maple (warm beige) at "
        "Medium tone with Plank layout. Surfaces the per-species "
        "palette differentiation alongside the existing 5 species."
    ),
    columns=[
        ColumnSpec("Mahogany", wood_factory(
            species=WOOD_MAHOGANY, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Ebony", wood_factory(
            species=WOOD_EBONY, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Ash", wood_factory(
            species=WOOD_ASH, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Maple", wood_factory(
            species=WOOD_MAPLE, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
    ],
    seed=7,
    params={"family": "Wood", "axis": "species-extra-1"},
))


register_catalog_page(CatalogPageSpec(
    name="species-extra-2",
    category="synthetic/floors/wood",
    description=(
        "Wood new species set 2 — Birch (very pale pink-cream), "
        "Teak (warm golden-brown), Bamboo (pale yellow-tan) at "
        "Medium tone with Plank layout."
    ),
    columns=[
        ColumnSpec("Birch", wood_factory(
            species=WOOD_BIRCH, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Teak", wood_factory(
            species=WOOD_TEAK, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
        ColumnSpec("Bamboo", wood_factory(
            species=WOOD_BAMBOO, layout=WOOD_PLANK, tone=WOOD_MEDIUM,
        )),
    ],
    seed=7,
    params={"family": "Wood", "axis": "species-extra-2"},
))


register_catalog_page(CatalogPageSpec(
    name="oak-tones-extra",
    category="synthetic/floors/wood",
    description=(
        "Wood Oak — two post-Phase-5 tones (Bleached, sun-faded "
        "paler than Light; Aged, weathered with grayer patina "
        "between Medium and Charred) at Plank layout across "
        "rect / octagon / circle shape rows."
    ),
    columns=[
        ColumnSpec("Bleached", wood_factory(
            species=WOOD_OAK, layout=WOOD_PLANK, tone=WOOD_BLEACHED,
        )),
        ColumnSpec("Aged", wood_factory(
            species=WOOD_OAK, layout=WOOD_PLANK, tone=WOOD_AGED,
        )),
    ],
    seed=7,
    params={"family": "Wood", "species": "Oak", "axis": "tones-extra"},
))


__all__ = []

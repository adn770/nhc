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
    WOOD_BASKETWEAVE, WOOD_CHARRED, WOOD_CHERRY, WOOD_DARK,
    WOOD_HERRINGBONE, WOOD_LIGHT, WOOD_MEDIUM, WOOD_OAK,
    WOOD_PARQUET, WOOD_PINE, WOOD_PLANK, WOOD_WALNUT,
    WOOD_WEATHERED,
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


__all__ = []

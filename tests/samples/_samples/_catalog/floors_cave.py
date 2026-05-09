"""Cave floor catalog page — 4 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    CAVE_BASALT, CAVE_CORAL, CAVE_CRYSTAL, CAVE_GRANITE,
    CAVE_ICE, CAVE_LAVA_ROCK, CAVE_LIMESTONE, CAVE_SANDSTONE,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    cave_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/floors/cave",
    description=(
        "Cave substrates — Limestone, Granite, Sandstone, Basalt — "
        "across rect / octagon / circle shape rows. Each style "
        "carries its (base, highlight, shadow) palette over the "
        "buffered-jittered cave-outline pipeline."
    ),
    columns=[
        ColumnSpec("Limestone", cave_factory(style=CAVE_LIMESTONE)),
        ColumnSpec("Granite", cave_factory(style=CAVE_GRANITE)),
        ColumnSpec("Sandstone", cave_factory(style=CAVE_SANDSTONE)),
        ColumnSpec("Basalt", cave_factory(style=CAVE_BASALT)),
    ],
    seed=7,
    params={"family": "Cave"},
))


register_catalog_page(CatalogPageSpec(
    name="styles-extra",
    category="synthetic/floors/cave",
    description=(
        "Cave post-Phase-5 substrates — Crystal (pale blue-violet "
        "mineral), Coral (pinkish-orange sea cave), Ice (frozen "
        "blue-white), LavaRock (blackened basalt with red glow) — "
        "across rect / octagon / circle shape rows. Same buffered-"
        "jittered cave-outline pipeline as the original 4 styles."
    ),
    columns=[
        ColumnSpec("Crystal", cave_factory(style=CAVE_CRYSTAL)),
        ColumnSpec("Coral", cave_factory(style=CAVE_CORAL)),
        ColumnSpec("Ice", cave_factory(style=CAVE_ICE)),
        ColumnSpec("LavaRock", cave_factory(style=CAVE_LAVA_ROCK)),
    ],
    seed=7,
    params={"family": "Cave", "axis": "styles-extra"},
))


__all__ = []

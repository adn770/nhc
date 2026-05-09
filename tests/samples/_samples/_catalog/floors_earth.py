"""Earth floor catalog page — 4 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    EARTH_COBBLE_DIRT, EARTH_CROP_FIELD, EARTH_DIRT, EARTH_GRASS,
    EARTH_GRAVEL, EARTH_MUD, EARTH_SAND, EARTH_SNOW,
)

from ._builder import (
    CatalogPageSpec, ColumnSpec,
    earth_factory, register_catalog_page,
)


register_catalog_page(CatalogPageSpec(
    name="styles",
    category="synthetic/floors/earth",
    description=(
        "Earth substrates — Dirt, Grass, Sand, Mud — across rect / "
        "octagon / circle shape rows. The four outdoor surface "
        "fills."
    ),
    columns=[
        ColumnSpec("Dirt", earth_factory(style=EARTH_DIRT)),
        ColumnSpec("Grass", earth_factory(style=EARTH_GRASS)),
        ColumnSpec("Sand", earth_factory(style=EARTH_SAND)),
        ColumnSpec("Mud", earth_factory(style=EARTH_MUD)),
    ],
    seed=7,
    params={"family": "Earth"},
))


register_catalog_page(CatalogPageSpec(
    name="styles-extra",
    category="synthetic/floors/earth",
    description=(
        "Earth post-Phase-5 substrates — Snow (faint-blue white), "
        "Gravel (mottled gray-brown), CobbleDirt (rough beaten "
        "dirt with cobble pebbles), CropField (tilled soil with "
        "greenish chaff hint) — across rect / octagon / circle "
        "shape rows."
    ),
    columns=[
        ColumnSpec("Snow", earth_factory(style=EARTH_SNOW)),
        ColumnSpec("Gravel", earth_factory(style=EARTH_GRAVEL)),
        ColumnSpec("CobbleDirt", earth_factory(style=EARTH_COBBLE_DIRT)),
        ColumnSpec("CropField", earth_factory(style=EARTH_CROP_FIELD)),
    ],
    seed=7,
    params={"family": "Earth", "axis": "styles-extra"},
))


__all__ = []

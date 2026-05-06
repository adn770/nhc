"""Earth floor catalog page — 4 styles × 3 shapes."""

from __future__ import annotations

from nhc.rendering.emit.materials import (
    EARTH_DIRT, EARTH_GRASS, EARTH_MUD, EARTH_SAND,
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


__all__ = []

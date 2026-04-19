"""Site composition: Buildings + walkable surface + optional enclosure.

See ``design/building_generator.md`` section 5 for the full site
vocabulary. A ``Site`` is the hex-level exploration unit returned
by each site assembler (``tower``, ``farm``, ``mansion``, ``keep``,
``town``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.dungeon.building import Building
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile


@dataclass
class Enclosure:
    """Closed outer wall around a Site.

    ``kind`` is ``"fortification"`` for keep-style walls and
    ``"palisade"`` for town-style. ``polygon`` is the enclosure
    vertex list in tile coordinates. ``gates`` is a list of
    ``(x, y, length_tiles)`` specifying gate midpoints along the
    polygon edges.
    """

    kind: str
    polygon: list[tuple[int, int]]
    gates: list[tuple[int, int, int]] = field(default_factory=list)


@dataclass
class Site:
    """A hex-level exploration site.

    ``buildings`` is the list of :class:`Building` instances that
    make up the site. ``surface`` is the outdoor walkable level
    (street / field / garden tiles live here). ``enclosure`` is
    ``None`` for unwalled sites (tower, farm, mansion).

    ``building_doors`` maps a surface ``(sx, sy)`` tile (one step
    outside the building's footprint) to ``(building_id, bx, by)``
    -- the building-ground door tile reached by crossing that
    surface door. ``(sx, sy)`` and ``(bx, by)`` are adjacent
    (distance 1); the surface tile is on the walkable outdoor
    area, the building tile is on the building's perimeter.
    ``interior_doors`` links adjacent buildings (mansions only):
    ``(from_building_id, fx, fy)`` -> ``(to_building_id, tx, ty)``
    -- the sibling building's mirrored door tile.
    """

    id: str
    kind: str
    buildings: list[Building]
    surface: Level
    enclosure: Enclosure | None = None
    building_doors: dict[
        tuple[int, int], tuple[str, int, int]
    ] = field(default_factory=dict)
    interior_doors: dict[
        tuple[str, int, int], tuple[str, int, int]
    ] = field(default_factory=dict)


# ── Surface door painter ─────────────────────────────────────


def outside_neighbour(
    building: Building, bx: int, by: int,
) -> tuple[int, int] | None:
    """Return the 4-neighbour of ``(bx, by)`` that is outside the
    building's footprint, or ``None`` when every neighbour is
    inside the footprint (shouldn't happen for perimeter tiles)."""
    footprint = building.base_shape.floor_tiles(building.base_rect)
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = bx + dx, by + dy
        if (nx, ny) in footprint:
            continue
        return (nx, ny)
    return None


def paint_surface_doors(
    site: Site, default_surface: SurfaceType,
) -> None:
    """Paint surface-side door tiles for every building entry.

    For each ``(sx, sy)`` in ``site.building_doors``, replace the
    surface tile at that coord with a walkable ``FLOOR`` + closed
    door. The surface door lives one tile outside the building's
    footprint so it sits naturally on the walkable outdoor area
    and carries the site's ``default_surface`` type (STREET for
    keep/town, GARDEN for mansion, FIELD for farm). Coordinates
    outside the surface bounds are skipped, which lets tower
    sites (tiny framing surface) call this without error.
    """
    surface = site.surface
    for (sx, sy) in site.building_doors.keys():
        if not surface.in_bounds(sx, sy):
            continue
        surface.tiles[sy][sx] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_closed",
            surface_type=default_surface,
        )


# ── Assembler dispatcher ─────────────────────────────────────

SITE_KINDS = ("tower", "farm", "mansion", "keep", "town")


def assemble_site(
    kind: str, site_id: str, rng: random.Random,
) -> Site:
    """Dispatch ``kind`` to the matching site assembler.

    Valid ``kind`` values are :data:`SITE_KINDS`. Any other value
    raises ``ValueError``.
    """
    # Deferred imports keep this module cheap to import and avoid
    # circular references back to Building / Level helpers.
    if kind == "tower":
        from nhc.dungeon.sites.tower import assemble_tower
        return assemble_tower(site_id, rng)
    if kind == "farm":
        from nhc.dungeon.sites.farm import assemble_farm
        return assemble_farm(site_id, rng)
    if kind == "mansion":
        from nhc.dungeon.sites.mansion import assemble_mansion
        return assemble_mansion(site_id, rng)
    if kind == "keep":
        from nhc.dungeon.sites.keep import assemble_keep
        return assemble_keep(site_id, rng)
    if kind == "town":
        from nhc.dungeon.sites.town import assemble_town
        return assemble_town(site_id, rng)
    raise ValueError(f"unknown site kind: {kind!r}")

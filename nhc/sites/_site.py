"""Site composition: Buildings + walkable surface + optional enclosure.

See ``design/building_generator.md`` section 5 for the full site
vocabulary. A ``Site`` is the hex-level exploration unit returned
by each site assembler (``tower``, ``farm``, ``mansion``, ``keep``,
``town``).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nhc.dungeon.building import Building
from nhc.dungeon.model import Level, SurfaceType, Terrain, Tile

if TYPE_CHECKING:
    from nhc.hexcrawl.model import Biome


@dataclass
class InteriorDoorLink:
    """Paired door tiles on mirrored perimeter positions of two
    adjacent buildings, on the same floor index.

    Stepping onto either tile teleports to the other (same
    mechanism as surface entry doors). Door state (open / closed,
    ``opened_at_turn``) must stay in sync across the pair — the
    door action and ``tick_doors`` propagate changes through the
    site via :func:`sync_linked_door_state`.

    Invariant: ``floor < min(len(A.floors), len(B.floors))`` —
    links only exist on floors present on both buildings.
    """

    from_building: str
    to_building: str
    floor: int
    from_tile: tuple[int, int]
    to_tile: tuple[int, int]


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
    # Structured per-floor cross-building links (M15). The legacy
    # interior_doors dict stays for back-compat with existing
    # movement / door-crossing code; interior_door_links is the
    # new list iterator paths should prefer and is what
    # sync_linked_door_state uses to propagate state.
    interior_door_links: list[InteriorDoorLink] = field(
        default_factory=list,
    )
    # Cluster-pack output (towns only, M-town-redesign Phase 1+).
    # Phase 2 / 3 / 5 read this to thread streets through the gaps,
    # bias door placement and reserve the centerpiece patch. Other
    # site kinds leave it empty.
    cluster_plans: list = field(default_factory=list)


# ── Surface door painter ─────────────────────────────────────


_COMPASS: dict[tuple[int, int], str] = {
    (0, -1): "north",
    (0, 1): "south",
    (1, 0): "east",
    (-1, 0): "west",
}


def _compass(dx: int, dy: int) -> str:
    """Return the compass edge name for an orthogonal unit delta.

    Used to tag ``Tile.door_side`` when painting surface doors, so
    the web client's wall-mask code can snap the door to the
    building-side edge instead of the tile centre. Raises
    ``ValueError`` for non-orthogonal or zero deltas -- callers
    always have ``(sx, sy)`` and ``(bx, by)`` one step apart.
    """
    side = _COMPASS.get((dx, dy))
    if side is None:
        raise ValueError(
            f"non-orthogonal delta ({dx}, {dy}); "
            "surface door and building-side tile must be adjacent"
        )
    return side


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


def is_clipped_corner_tile(
    building: Building, bx: int, by: int,
) -> bool:
    """Detect tiles that sit at the diagonal "chamfer step" of
    an octagonal building (or any shape whose floor footprint
    drops a corner inside its own bounding rect).

    Returns True when *every* exterior 4-neighbour of
    ``(bx, by)`` lies INSIDE the building's bounding rect but
    OUTSIDE the floor footprint -- i.e. the tile sits on a
    diagonal step where two perpendicular sides face clipped
    void rather than the surface.

    Tiles whose exterior neighbours include at least one
    out-of-bbox direction (the "true exterior") are not flagged:
    they sit on a flat or near-flat side of the building and the
    door-side direction is unambiguous. Rectangular buildings
    never trigger this check (all bbox cells are floor).

    Used by ``_place_entry_door`` to reject tiles whose outward-
    facing direction would land inside the masonry chamfer.
    """
    rect = building.base_rect
    footprint = building.base_shape.floor_tiles(rect)
    has_clipped = False
    has_out_of_bbox = False
    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        nx, ny = bx + dx, by + dy
        if (nx, ny) in footprint:
            continue
        if (rect.x <= nx < rect.x2 and rect.y <= ny < rect.y2):
            has_clipped = True
        else:
            has_out_of_bbox = True
    return has_clipped and not has_out_of_bbox


def stamp_building_door(
    building: Building, bx: int, by: int,
    feature: str = "door_closed",
) -> None:
    """Mark ``(bx, by)`` on ``building.ground`` as a door with
    precise ``door_side`` metadata.

    The wall direction is taken from :func:`outside_neighbour` --
    the same call used to pick the matching surface-level door --
    so the building interior door and the surface door describe
    the *same physical wall* from their respective sides. No
    downstream heuristic has to guess orientation, which fixes
    the case reported in the live session where a corner door
    appeared on one wall from the outside and a different wall
    from the inside.

    Every site assembler should go through this helper instead of
    stamping ``tile.feature = "door_closed"`` directly.
    """
    stamp_building_door_on_floor(building, 0, bx, by, feature)


def stamp_building_door_on_floor(
    building: Building, floor_idx: int, bx: int, by: int,
    feature: str = "door_closed",
) -> None:
    """Stamp a door at ``(bx, by)`` on ``building.floors[floor_idx]``.

    Variant of :func:`stamp_building_door` that targets any floor
    (not just the ground). Used by the cross-building links in
    multi-floor town pairs where the link must land on each shared
    floor.
    """
    tile = building.floors[floor_idx].tiles[by][bx]
    tile.feature = feature
    nb = outside_neighbour(building, bx, by)
    if nb is None:
        return
    dx = nb[0] - bx
    dy = nb[1] - by
    if (dx, dy) in _COMPASS:
        tile.door_side = _COMPASS[(dx, dy)]


def paint_surface_doors(
    site: Site, default_surface: SurfaceType,
) -> None:
    """Paint surface-side door tiles for every building entry.

    For each ``(sx, sy)`` in ``site.building_doors``, stamp the
    surface tile at that coord as a walkable ``FLOOR`` + closed
    door. When the existing tile already carries a
    ``surface_type`` (the post-Phase-2 town surface tags STREET /
    GARDEN / FIELD per tile), that type is preserved so the door
    visually reads as part of its surrounding surface. Otherwise
    the helper falls back to ``default_surface`` -- the legacy
    "always-STREET / always-GARDEN / always-FIELD" behaviour for
    sites whose surface is uniform.
    """
    surface = site.surface
    for (sx, sy), (_bid, bx, by) in site.building_doors.items():
        if not surface.in_bounds(sx, sy):
            continue
        existing = surface.tiles[sy][sx]
        if (existing.terrain == Terrain.FLOOR
                and existing.surface_type is not None):
            surface_type = existing.surface_type
        else:
            surface_type = default_surface
        surface.tiles[sy][sx] = Tile(
            terrain=Terrain.FLOOR,
            feature="door_closed",
            surface_type=surface_type,
            door_side=_compass(bx - sx, by - sy),
        )


# ── Assembler dispatcher ─────────────────────────────────────

SITE_KINDS = (
    "tower", "farm", "mansion", "keep", "town",
    "temple", "cottage", "ruin", "mage_residence",
)


def sync_linked_door_state(
    site: "Site", building_id: str, tile_xy: tuple[int, int],
) -> None:
    """Propagate the door feature + ``opened_at_turn`` at
    ``(building_id, tile_xy)`` to its mirrored tile, if the tile is
    part of an :class:`InteriorDoorLink`.

    Called after open / close actions and after
    :func:`tick_doors` auto-closes a door so both sides of a
    link stay in sync. See ``design/building_interiors.md``
    section "Auto-close rule".
    """
    buildings = {b.id: b for b in site.buildings}
    src_b = buildings.get(building_id)
    if src_b is None:
        return
    for link in site.interior_door_links:
        if link.from_building == building_id and link.from_tile == tile_xy:
            other_id = link.to_building
            other_tile = link.to_tile
        elif link.to_building == building_id and link.to_tile == tile_xy:
            other_id = link.from_building
            other_tile = link.from_tile
        else:
            continue
        other_b = buildings.get(other_id)
        if other_b is None or not (
            0 <= link.floor < len(other_b.floors)
        ):
            continue
        src_tile = src_b.floors[link.floor].tiles[tile_xy[1]][tile_xy[0]]
        dst_tile = other_b.floors[link.floor].tiles[
            other_tile[1]
        ][other_tile[0]]
        dst_tile.feature = src_tile.feature
        dst_tile.opened_at_turn = src_tile.opened_at_turn


def populate_building_door_sides(site: "Site") -> None:
    """Fill any door tiles that still lack ``door_side``.

    Deprecated: every assembler now calls
    :func:`stamp_building_door` which sets ``door_side`` at
    generation time. Kept as a safety net so a future code path
    that hand-stamps ``feature = "door_closed"`` without the
    helper still ends up with a non-empty ``door_side`` via the
    dungeon-style heuristic (which is imprecise at corners but
    better than an empty string).
    """
    from nhc.dungeon.generators._doors import _compute_door_sides
    for b in site.buildings:
        for floor in b.floors:
            _compute_door_sides(floor)


def assemble_site(
    kind: str, site_id: str, rng: random.Random,
    size_class: str | None = None,
    biome: "Biome | None" = None,  # noqa: UP037
    mage_variant: bool = False,
) -> Site:
    """Dispatch ``kind`` to the matching site assembler.

    Valid ``kind`` values are :data:`SITE_KINDS`. Any other value
    raises ``ValueError``. ``size_class`` only applies to the
    ``town`` assembler (hamlet / village / town / city); it is
    ignored for every other kind. ``biome`` lets the town
    assembler apply per-biome overrides (see ``assemble_town``);
    other kinds ignore it for now. ``mage_variant`` toggles the
    mage-residence flavour on tower and mansion kinds.
    """
    # Deferred imports keep this module cheap to import and avoid
    # circular references back to Building / Level helpers.
    if kind == "tower":
        from nhc.sites.tower import assemble_tower
        site = assemble_tower(
            site_id, rng, biome=biome, mage_variant=mage_variant,
        )
    elif kind == "farm":
        from nhc.sites.farm import assemble_farm
        site = assemble_farm(site_id, rng)
    elif kind == "mansion":
        from nhc.sites.mansion import assemble_mansion
        site = assemble_mansion(
            site_id, rng, mage_variant=mage_variant,
        )
    elif kind == "keep":
        from nhc.sites.keep import assemble_keep
        site = assemble_keep(site_id, rng)
    elif kind == "town":
        from nhc.sites.town import assemble_town
        kwargs: dict = {}
        if size_class is not None:
            kwargs["size_class"] = size_class
        if biome is not None:
            kwargs["biome"] = biome
        site = assemble_town(site_id, rng, **kwargs)
    elif kind == "temple":
        from nhc.sites.temple import assemble_temple
        site = assemble_temple(site_id, rng, biome=biome)
    elif kind == "cottage":
        from nhc.sites.cottage import assemble_cottage
        site = assemble_cottage(site_id, rng, biome=biome)
    elif kind == "ruin":
        from nhc.sites.ruin import assemble_ruin
        site = assemble_ruin(site_id, rng, biome=biome)
    elif kind == "mage_residence":
        from nhc.sites.mage_residence import (
            assemble_mage_residence,
        )
        site = assemble_mage_residence(site_id, rng)
    else:
        raise ValueError(f"unknown site kind: {kind!r}")
    populate_building_door_sides(site)
    return site

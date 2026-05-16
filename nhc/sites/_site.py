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


def combined_building_bboxes(
    buildings: list[Building],
) -> set[tuple[int, int]]:
    """Return the union of every building's full bounding-rect tile set.

    For axis-aligned rect buildings, the bbox tile set equals the
    floor footprint. For octagon / circle / L-shape buildings, the
    bbox additionally covers the chamfer-void / notch cells that
    sit inside ``base_rect`` but outside ``floor_tiles()``.

    Multi-building site assemblers feed this into ``_pick_door_location``
    via the ``blocked`` arg so a door's outside-neighbour can never
    land inside another building's bbox -- the chamfer-void corridor
    between an octagon and an adjacent rect is masonry-adjacent and
    would render the surface door pinched against the diagonal wall.
    Compare with :func:`is_clipped_corner_tile`, which rejects tiles
    on the *building's own* clipped corners.
    """
    cells: set[tuple[int, int]] = set()
    for b in buildings:
        rect = b.base_rect
        for x in range(rect.x, rect.x2):
            for y in range(rect.y, rect.y2):
                cells.add((x, y))
    return cells


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
        # Phase 3a/3b: GARDEN / FIELD tiles render on Terrain.GRASS
        # so the theme grass tint paints under the overlay. Treat
        # FLOOR or GRASS as "this tile is already part of the
        # painted surface" and preserve its surface_type + terrain.
        if (existing.terrain in (Terrain.FLOOR, Terrain.GRASS)
                and existing.surface_type is not None):
            surface_type = existing.surface_type
            terrain = existing.terrain
        else:
            surface_type = default_surface
            terrain = (
                Terrain.GRASS
                if default_surface in (
                    SurfaceType.GARDEN, SurfaceType.FIELD,
                )
                else Terrain.FLOOR
            )
        surface.tiles[sy][sx] = Tile(
            terrain=terrain,
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
    # Convert the site surface's outer 1-tile VOID buffer to
    # GRASS / FIELD so the canvas reads "site sits in countryside"
    # rather than "framed art on paper". Town settlements handle
    # their own grass ring (1 or 2 tiles depending on enclosure)
    # internally, so this only fires for non-town site kinds.
    if kind != "town":
        paint_outer_grass_ring(site.surface, ring_width=1)
    return site


def paint_outer_grass_ring(level: "Level", ring_width: int) -> None:
    """Convert the outer ``ring_width``-tile VOID border of a
    site surface to GRASS / FIELD.

    Replaces the historic 1-tile VOID buffer at the canvas edge
    (per ``design/level_surface_layout.md``) with renderable grass
    tiles so the final canvas reads "site in countryside" rather
    than "framed art on paper". Settlements with palisade /
    fortification use ``ring_width=2`` to leave room for trees /
    bushes outside the wall; every other site (and hamlet) uses
    ``ring_width=1`` — just the existing canvas-edge buffer flips
    from VOID to grass.

    Only VOID tiles are touched: enclosure walls, building
    footprints, or any other content that already paints into
    the perimeter is left alone.
    """
    h = level.height
    w = level.width
    for y in range(h):
        for x in range(w):
            if (
                x >= ring_width and x < w - ring_width
                and y >= ring_width and y < h - ring_width
            ):
                continue
            tile = level.tiles[y][x]
            if tile.terrain is Terrain.VOID:
                level.tiles[y][x] = Tile(
                    terrain=Terrain.GRASS,
                    surface_type=SurfaceType.FIELD,
                )


def plant_formal_garden(
    site: "Site", *, tree_spacing: int = 3, flower: bool = True,
) -> None:
    """Lay out a well-kept formal garden on a site's surface.

    Deterministic and geometric, never a random scatter:

    * a continuous ``bush`` hedge traces the playable border ring
      (just inside the 1-tile VOID margin),
    * a ``flower`` border runs the ring immediately inside the
      hedge (a parterre edge) when ``flower`` is set,
    * ``tree`` specimens sit on a regular lattice centred on the
      surface (``tree_spacing`` apart on both axes, mirror-
      symmetric), kept one tile clear of every building so canopies
      never bleed onto a wall / roof,
    * a 1-wide path is cleared from each building door straight out
      to the nearest border, with a matching gap cut in the hedge.

    Only ``Terrain.GRASS`` tiles are planted, so the caller must
    have painted the garden surface first.
    """
    surface = site.surface
    w, h = surface.width, surface.height

    footprint: set[tuple[int, int]] = set()
    for b in site.buildings:
        footprint |= b.base_shape.floor_tiles(b.base_rect)
    halo: set[tuple[int, int]] = set(footprint)
    for (fx, fy) in footprint:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            halo.add((fx + dx, fy + dy))

    if footprint:
        gx = sum(p[0] for p in footprint) / len(footprint)
        gy = sum(p[1] for p in footprint) / len(footprint)
    else:
        gx, gy = w / 2.0, h / 2.0

    # Straight kept path from each door out to the nearest border.
    path: set[tuple[int, int]] = set()
    for (sx, sy) in site.building_doors:
        if abs(sx - gx) >= abs(sy - gy):
            step = (1 if sx >= gx else -1, 0)
        else:
            step = (0, 1 if sy >= gy else -1)
        px, py = sx, sy
        while 1 <= px <= w - 2 and 1 <= py <= h - 2:
            path.add((px, py))
            px += step[0]
            py += step[1]

    def _plantable(x: int, y: int) -> bool:
        if not (1 <= x <= w - 2 and 1 <= y <= h - 2):
            return False
        tile = surface.tiles[y][x]
        if tile.terrain is not Terrain.GRASS:
            return False
        if tile.feature is not None:
            return False
        if (x, y) in footprint or (x, y) in path:
            return False
        return True

    # Hedge: the playable border ring.
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if (x in (1, w - 2) or y in (1, h - 2)) and _plantable(x, y):
                surface.tiles[y][x].feature = "bush"

    # Flower parterre: the ring one tile inside the hedge.
    if flower:
        for y in range(2, h - 2):
            for x in range(2, w - 2):
                on_inner = x in (2, w - 3) or y in (2, h - 3)
                if on_inner and _plantable(x, y):
                    surface.tiles[y][x].feature = "flower"

    # Tree lattice, centred so it is mirror-symmetric; the two
    # border rings are left to the hedge and the flower parterre.
    cx, cy = w // 2, h // 2
    sp = tree_spacing
    for y in range(3, h - 3):
        for x in range(3, w - 3):
            if (x - cx) % sp or (y - cy) % sp:
                continue
            if (x, y) in halo:
                continue
            if _plantable(x, y):
                surface.tiles[y][x].feature = "tree"

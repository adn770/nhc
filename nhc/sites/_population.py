"""Declarative site population system.

A :data:`SITE_POPULATION` table maps ``(kind, tier)`` pairs to a
list of :class:`PopulationEntry` records describing what entities
to place and *where* (interior of the first building, near a
building door, anywhere on the open surface). The resolver
:func:`resolve_site_population` rolls those entries onto a
freshly-assembled :class:`Site` and returns a list of concrete
:class:`Placement` records (per-level coords). The populator
:func:`populate_site_placements` consumes those records and
spawns the matching ECS entities with mutation-replay tracking.

The resolver is shared by every site kind that opts in. Today
farms (sub-hex TINY + macro SMALL) flow through this path; other
kinds keep their existing populator wiring until they are
migrated.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nhc.dungeon.model import Terrain
from nhc.sites._types import SiteTier

if TYPE_CHECKING:
    from nhc.sites._site import Site


@dataclass(frozen=True)
class PopulationEntry:
    """One entry in a site's population spec.

    ``placement`` selects the placement strategy (see
    :func:`_pick_tile`):

    * ``"in_building_0"`` — interior of ``site.buildings[0].ground``
    * ``"near_building_0_door"`` — surface tile adjacent to one of
      buildings[0]'s outside doors
    * ``"on_open_surface"`` — random surface FLOOR tile away from
      any building footprint
    * ``"near_feature"`` — surface tile adjacent to the centerpiece
      passed through ``feature_tile`` to the resolver (well /
      shrine / signpost). No-op when the caller doesn't supply a
      feature tile.

    ``count_min`` / ``count_max`` give an inclusive range; the
    resolver rolls once per entry at site-generation time.
    """

    entity_id: str
    placement: str
    count_min: int = 1
    count_max: int = 1


@dataclass(frozen=True)
class Placement:
    """Resolved entity placement: registry id + level + tile."""

    entity_id: str
    level_id: str
    x: int
    y: int


# (kind, tier) -> [PopulationEntry, ...]. Kinds not in this table
# either stay on their existing populator wiring or get an empty
# population (no NPCs at all).
SITE_POPULATION: dict[tuple[str, SiteTier], list[PopulationEntry]] = {
    ("farm", SiteTier.TINY): [
        PopulationEntry("farmer", "in_building_0", 1, 1),
        PopulationEntry("farmhand", "on_open_surface", 1, 2),
    ],
    ("farm", SiteTier.SMALL): [
        PopulationEntry("farmer", "in_building_0", 1, 1),
        PopulationEntry("farmhand", "on_open_surface", 2, 4),
    ],
    # Shrines / standing stones / cairns: occasional pilgrim
    # praying at the centerpiece. count_min=0 makes the placement
    # genuinely rare so most sacred sites remain solitary.
    ("sacred", SiteTier.TINY): [
        PopulationEntry("pilgrim", "near_feature", 0, 1),
    ],
    ("sacred", SiteTier.SMALL): [
        PopulationEntry("pilgrim", "near_feature", 0, 1),
    ],
    # Wells / signposts on the road: a campsite_traveller stops to
    # rest, doubling as a rumour vendor at a tiny sub-hex site.
    ("wayside", SiteTier.TINY): [
        PopulationEntry(
            "campsite_traveller", "near_feature", 0, 1,
        ),
    ],
    ("wayside", SiteTier.SMALL): [
        PopulationEntry(
            "campsite_traveller", "near_feature", 0, 1,
        ),
    ],
    # Mansion: the lord stays in the main hall (buildings[0]); a
    # household servant tends the garden surface around the
    # estate. Buildings 1+ stay empty for now -- can extend with
    # cook / valet specs once the placement strategy supports
    # in_building_n.
    ("mansion", SiteTier.MEDIUM): [
        PopulationEntry("noble", "in_building_0", 1, 1),
        PopulationEntry("villager", "on_open_surface", 0, 1),
    ],
    # Tower: a hermit / scholar lives on the ground floor. Mage
    # towers and regular towers share the spec for now -- the
    # mage_variant flag is internal to the assembler and doesn't
    # leak into the kind name.
    ("tower", SiteTier.TINY): [
        PopulationEntry("hermit", "in_building_0", 1, 1),
    ],
}


def resolve_site_population(
    site: "Site",
    kind: str,
    tier: SiteTier,
    rng: random.Random,
    *,
    reserved: "set[tuple[int, int]] | None" = None,
    feature_tile: "tuple[int, int] | None" = None,
) -> list[Placement]:
    """Roll the ``(kind, tier)`` spec onto concrete tiles.

    Returns a list of :class:`Placement` records — one per
    successfully-placed entity. Entries that can't find a free
    tile are silently dropped (a TINY farm with no surface FIELD
    tiles, etc.). The ``reserved`` set holds surface tiles that
    must not be claimed (e.g. the player's entry tile);
    ``feature_tile`` is the centerpiece coord used by the
    ``near_feature`` placement strategy (well / shrine / signpost).
    """
    entries = SITE_POPULATION.get((kind, tier), [])
    if not entries:
        return []

    placements: list[Placement] = []
    surface_used: set[tuple[int, int]] = set(reserved or set())
    if feature_tile is not None:
        surface_used.add(feature_tile)
    building_used: dict[int, set[tuple[int, int]]] = {}

    for entry in entries:
        count = rng.randint(entry.count_min, entry.count_max)
        for _ in range(count):
            placement = _pick_tile(
                site, entry, rng,
                surface_used, building_used,
                feature_tile=feature_tile,
            )
            if placement is None:
                continue
            placements.append(placement)
    return placements


def populate_site_placements(
    world,
    placements: list[Placement],
    *,
    mutations: "dict | None" = None,
) -> list[int]:
    """Spawn ``placements`` into ``world``; return new entity ids.

    Each entity gets a :class:`SubHexStableId` keyed on
    ``{entity_id}_{level_id}_{x}_{y}`` so placements on different
    levels (surface + farmhouse interior) don't collide. Killed
    entries listed in ``mutations["killed"]`` are skipped on
    replay so a dead farmer stays dead across cache eviction.
    """
    from nhc.entities.components import (
        BlocksMovement, Position, SubHexStableId,
    )
    from nhc.entities.registry import EntityRegistry

    muts = mutations or {}
    killed = set(muts.get("killed", []))
    spawned: list[int] = []

    for p in placements:
        sid = f"{p.entity_id}_{p.level_id}_{p.x}_{p.y}"
        if sid in killed:
            continue
        try:
            comps = EntityRegistry.get_creature(p.entity_id)
        except KeyError:
            continue
        comps["BlocksMovement"] = BlocksMovement()
        comps["Position"] = Position(
            x=p.x, y=p.y, level_id=p.level_id,
        )
        comps["SubHexStableId"] = SubHexStableId(stable_id=sid)
        # Wandering NPCs (errand AI) anchor at the spawn tile so
        # they stay near where the population spec dropped them
        # instead of drifting across the whole farm field /
        # mansion garden / town square. Idle NPCs (no Errand
        # component) skip this branch and stay rooted.
        errand = comps.get("Errand")
        if errand is not None:
            errand.anchor_x = p.x
            errand.anchor_y = p.y
        spawned.append(world.create_entity(comps))
    return spawned


# -- placement strategies ------------------------------------------


def _pick_tile(
    site: "Site",
    entry: PopulationEntry,
    rng: random.Random,
    surface_used: set[tuple[int, int]],
    building_used: dict[int, set[tuple[int, int]]],
    *,
    feature_tile: "tuple[int, int] | None" = None,
) -> "Placement | None":
    if entry.placement == "in_building_0":
        if not site.buildings:
            return None
        building = site.buildings[0]
        used = building_used.setdefault(0, set())
        xy = _pick_interior_tile(building, used)
        if xy is None:
            return None
        used.add(xy)
        return Placement(
            entity_id=entry.entity_id,
            level_id=building.ground.id,
            x=xy[0], y=xy[1],
        )
    if entry.placement == "near_building_0_door":
        if not site.buildings:
            return None
        building = site.buildings[0]
        xy = _pick_door_adjacent_tile(
            site, building, rng, surface_used,
        )
        if xy is None:
            return None
        return Placement(
            entity_id=entry.entity_id,
            level_id=site.surface.id,
            x=xy[0], y=xy[1],
        )
    if entry.placement == "on_open_surface":
        xy = _pick_open_surface_tile(site, rng, surface_used)
        if xy is None:
            return None
        return Placement(
            entity_id=entry.entity_id,
            level_id=site.surface.id,
            x=xy[0], y=xy[1],
        )
    if entry.placement == "near_feature":
        if feature_tile is None:
            return None
        xy = _pick_feature_adjacent_tile(
            site, feature_tile, rng, surface_used,
        )
        if xy is None:
            return None
        return Placement(
            entity_id=entry.entity_id,
            level_id=site.surface.id,
            x=xy[0], y=xy[1],
        )
    return None


def _pick_interior_tile(
    building, used: set[tuple[int, int]],
) -> "tuple[int, int] | None":
    """Closest-to-centre FLOOR tile inside the building, no feature."""
    ground = building.ground
    cx = building.base_rect.x + building.base_rect.width // 2
    cy = building.base_rect.y + building.base_rect.height // 2
    candidates: list[tuple[int, int]] = []
    for y in range(ground.height):
        for x in range(ground.width):
            tile = ground.tile_at(x, y)
            if tile is None or tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature is not None:
                continue
            if (x, y) in used:
                continue
            candidates.append((x, y))
    if not candidates:
        return None
    candidates.sort(
        key=lambda xy: abs(xy[0] - cx) + abs(xy[1] - cy),
    )
    return candidates[0]


def _pick_door_adjacent_tile(
    site, building, rng: random.Random,
    surface_used: set[tuple[int, int]],
) -> "tuple[int, int] | None":
    """Surface tile orthogonal to one of building's outside doors."""
    surface = site.surface
    door_outsides = [
        outside for outside, (bid, _bx, _by)
        in site.building_doors.items()
        if bid == building.id
    ]
    candidates: list[tuple[int, int]] = []
    for (dx, dy) in door_outsides:
        for (ax, ay) in (
            (dx - 1, dy), (dx + 1, dy),
            (dx, dy - 1), (dx, dy + 1),
        ):
            tile = surface.tile_at(ax, ay)
            if tile is None or tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature is not None:
                continue
            if (ax, ay) in surface_used:
                continue
            candidates.append((ax, ay))
    if not candidates:
        return None
    pick = rng.choice(candidates)
    surface_used.add(pick)
    return pick


def _pick_feature_adjacent_tile(
    site, feature_tile: tuple[int, int],
    rng: random.Random,
    surface_used: set[tuple[int, int]],
) -> "tuple[int, int] | None":
    """Surface FLOOR tile orthogonally adjacent to ``feature_tile``."""
    fx, fy = feature_tile
    surface = site.surface
    candidates: list[tuple[int, int]] = []
    for (ax, ay) in (
        (fx - 1, fy), (fx + 1, fy),
        (fx, fy - 1), (fx, fy + 1),
    ):
        if (ax, ay) in surface_used:
            continue
        tile = surface.tile_at(ax, ay)
        if tile is None or tile.terrain != Terrain.FLOOR:
            continue
        if tile.feature is not None:
            continue
        candidates.append((ax, ay))
    if not candidates:
        return None
    pick = rng.choice(candidates)
    surface_used.add(pick)
    return pick


def _pick_open_surface_tile(
    site, rng: random.Random,
    surface_used: set[tuple[int, int]],
) -> "tuple[int, int] | None":
    """Random open surface FLOOR tile away from any building."""
    surface = site.surface
    blocked: set[tuple[int, int]] = set()
    for b in site.buildings:
        footprint = b.base_shape.floor_tiles(b.base_rect)
        # Block the building footprint plus a one-tile buffer ring
        # so NPCs don't end up sitting on the doorstep.
        for (bx, by) in footprint:
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    blocked.add((bx + ddx, by + ddy))
    candidates: list[tuple[int, int]] = []
    for y in range(surface.height):
        for x in range(surface.width):
            if (x, y) in surface_used:
                continue
            if (x, y) in blocked:
                continue
            tile = surface.tile_at(x, y)
            if tile is None or tile.terrain != Terrain.FLOOR:
                continue
            if tile.feature is not None:
                continue
            candidates.append((x, y))
    if not candidates:
        return None
    pick = rng.choice(candidates)
    surface_used.add(pick)
    return pick

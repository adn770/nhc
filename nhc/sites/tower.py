"""Tower site assembler.

See ``design/building_generator.md`` section 5.1. A tower is one
Building with 2-6 floors sharing a circular, octagonal, or square
base shape. No enclosure. One entry door on the ground-floor
perimeter. Optional subterranean descent (~30% of towers). The
topmost floor is wood when the tower has 3+ floors; otherwise
stone throughout.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    build_floors_with_stairs,
)
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, Rect, RectShape, RoomShape,
    Terrain,
)
from nhc.sites._site import (
    Site, is_clipped_corner_tile, outside_neighbour,
    stamp_building_door,
)
from nhc.sites._types import SiteTier
from nhc.hexcrawl.model import Biome, DungeonRef


# ── Tower tunable constants ───────────────────────────────────

TOWER_SIZE_RANGE = (7, 11)                  # base rect width = height
TOWER_FLOOR_COUNT_RANGE = (2, 6)
TOWER_DESCENT_PROBABILITY = 0.3
TOWER_DESCENT_TEMPLATE = "procedural:crypt"
TOWER_SHAPE_POOL = ("circle", "octagon", "square")


def assemble_tower(
    site_id: str, rng: random.Random,
    biome: Biome | None = None,
    mage_variant: bool = False,
    *, tier: SiteTier = SiteTier.TINY,
) -> Site:
    """Assemble a tower site from ``rng``.

    Returns a :class:`Site` with exactly one :class:`Building`, no
    enclosure, and a small square ``surface`` level framing the
    tower footprint. Interior rendering is handled by
    ``render_floor_svg`` per floor and the building-wall SVG
    renderers in later integration milestones.

    ``biome`` is an optional :class:`Biome` that lets the
    assembler apply per-biome overrides matching v1's tile-only
    split (design/biome_features.md §8). Forest watchtowers cap
    at 2 floors and stamp ``roof_material="wood"`` on the
    Building; mountain towers force every floor's wall + interior
    to stone. All other biomes fall through to the unmodified
    defaults.

    When ``mage_variant`` is True the tower is always octagonal
    and every interior floor receives one teleporter pair — the
    mage's wayfinding trick. Mage towers keep biome-driven
    material overrides so a mountain mage tower stays stone.

    ``tier`` is accepted for the unified ``Game.enter_site``
    dispatcher API (M6b). Today only ``TINY`` is supported -- the
    tower's surface dim is computed from the building's base rect,
    not from a fixed footprint table.
    """
    if tier is not SiteTier.TINY:
        raise ValueError(
            f"tower only supports SiteTier.TINY; got {tier!r}",
        )
    if mage_variant:
        shape_key = "octagon"
    else:
        shape_key = rng.choice(TOWER_SHAPE_POOL)
    size = rng.randint(*TOWER_SIZE_RANGE)
    base_rect = Rect(1, 1, size, size)

    base_shape: RoomShape
    if shape_key == "circle":
        base_shape = CircleShape()
    elif shape_key == "octagon":
        base_shape = OctagonShape()
    else:
        base_shape = RectShape()

    n_floors = rng.randint(*TOWER_FLOOR_COUNT_RANGE)
    if biome is Biome.FOREST:
        # Forest watchtowers read as short wooden spotter
        # platforms, not full stone towers.
        n_floors = min(2, n_floors)

    descent: DungeonRef | None = None
    if rng.random() < TOWER_DESCENT_PROBABILITY:
        descent = DungeonRef(template=TOWER_DESCENT_TEMPLATE)

    mountain = biome is Biome.MOUNTAIN
    interior_floor_default = "stone"
    wall_material = "stone" if mountain else "brick"
    roof_material: str | None = None
    if biome is Biome.FOREST:
        roof_material = "wood"

    building_id = f"{site_id}_tower"
    # Circle towers route through SectorPartitioner; square
    # towers split into two rooms via DividedPartitioner. Octagon
    # towers borrow tower_circle since SectorPartitioner falls
    # back to SingleRoom for non-circle shapes.
    if shape_key == "circle":
        archetype = "tower_circle"
    elif shape_key == "octagon":
        archetype = "tower_circle"
    else:
        archetype = "tower_square"
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_tower_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            archetype=archetype,
            required_walkable=req,
        ),
    )

    if not mountain and n_floors >= 3:
        floors[-1].interior_floor = "wood"

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material=wall_material,
        interior_floor=interior_floor_default,
        interior_wall_material=(
            ARCHETYPE_CONFIG[archetype].interior_wall_material
        ),
        roof_material=roof_material,
    )
    building.stair_links = stair_links
    door_xy = _place_entry_door(building, rng)
    building.validate()

    surface = Level.create_empty(
        f"{site_id}_surface", f"{site_id} surface", 0,
        base_rect.x + base_rect.width + 2,
        base_rect.y + base_rect.height + 2,
    )

    site = Site(
        id=site_id,
        kind="tower",
        buildings=[building],
        surface=surface,
        enclosure=None,
    )
    if door_xy is not None:
        neighbour = outside_neighbour(building, *door_xy)
        if neighbour is not None:
            site.building_doors[neighbour] = (
                building.id, door_xy[0], door_xy[1],
            )
    if mage_variant:
        _stamp_mage_teleporters(building, rng)
    return site


def _stamp_mage_teleporters(
    building: Building, rng: random.Random,
) -> None:
    """Stamp one teleporter pair on each floor of a mage tower.

    Picks two floor tiles on the floor that are as far apart as
    possible (by chebyshev distance) and marks them with feature
    ``teleporter_pad``, registering the pair in the floor's
    ``teleporter_pairs`` map so the post-move hook can transit
    the player between them.
    """
    for floor in building.floors:
        candidates: list[tuple[int, int]] = []
        for y in range(floor.height):
            for x in range(floor.width):
                tile = floor.tiles[y][x]
                if tile.terrain is not Terrain.FLOOR:
                    continue
                if tile.feature is not None:
                    continue
                candidates.append((x, y))
        if len(candidates) < 2:
            continue
        # Pick the most-separated pair so the teleport is visibly
        # useful (walking to the sibling would take several turns).
        best: tuple[int, int, int, int] | None = None
        best_d = -1
        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                d = max(abs(a[0] - b[0]), abs(a[1] - b[1]))
                if d > best_d:
                    best_d = d
                    best = (a[0], a[1], b[0], b[1])
        if best is None:
            continue
        ax, ay, bx, by = best
        floor.tiles[ay][ax].feature = "teleporter_pad"
        floor.tiles[by][bx].feature = "teleporter_pad"
        floor.teleporter_pairs[(ax, ay)] = (bx, by)
        floor.teleporter_pairs[(bx, by)] = (ax, ay)


def _build_tower_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    archetype: str,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    """Build a tower floor via the archetype's registered partitioner."""
    return build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype=archetype,
        tags=["tower_interior"],
        required_walkable=required_walkable,
    )


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    """Mark one ground-floor perimeter tile as ``door_closed``.

    Returns the ``(x, y)`` of the placed door, or ``None`` when no
    eligible perimeter tile exists (small shape edge-case).
    """
    ground = building.ground
    perim = building.shared_perimeter()
    candidates: list[tuple[int, int]] = []
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        # Reject chamfer steps -- circle towers put diagonal
        # masonry across these tiles, so a tile-aligned door
        # reads ambiguously.
        if is_clipped_corner_tile(building, px, py):
            continue
        # Prefer perimeter tiles with a WALL neighbour outside the
        # building -- those face the surface.
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if not ground.in_bounds(nx, ny):
                continue
            if ground.tiles[ny][nx].terrain == Terrain.WALL:
                candidates.append((px, py))
                break
    if not candidates:
        return None
    dx, dy = rng.choice(sorted(candidates))
    stamp_building_door(building, dx, dy)
    return (dx, dy)

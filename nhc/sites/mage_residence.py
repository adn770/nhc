"""Mage residence assembler.

See ``design/building_interiors.md`` and ``design/building_generator.md``.
A mage residence is a single tower-like building drawn from the
``mage_residence`` archetype: octagon or circle footprint sized
9-13, partitioned with the enriched SectorPartitioner so the
"main" sector rotates per floor (spiral progression).
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
    CircleShape, Level, OctagonShape, Rect, RoomShape, Terrain,
)
from nhc.sites._site import (
    Site, is_clipped_corner_tile, outside_neighbour,
    stamp_building_door,
)
from nhc.sites._types import SiteTier
from nhc.hexcrawl.model import DungeonRef


MAGE_SIZE_RANGE = (9, 13)
MAGE_FLOOR_COUNT_RANGE = (2, 4)
MAGE_DESCENT_PROBABILITY = 0.4
MAGE_DESCENT_TEMPLATE = "procedural:crypt"
MAGE_SHAPE_POOL = ("octagon", "circle")


def assemble_mage_residence(
    site_id: str, rng: random.Random,
    *, tier: SiteTier = SiteTier.TINY,
) -> Site:
    """Assemble a mage-residence site.

    Returns a :class:`Site` with one :class:`Building` whose
    floors are partitioned by the enriched SectorPartitioner, so
    the "main" sector rotates per floor and one door drops on
    alternating floors — the layout reads as a spiral tower.

    ``tier`` is accepted for the unified ``Game.enter_site``
    dispatcher API (M6b). Today only ``TINY`` is supported -- the
    surface dim is computed from the building's base rect.
    """
    if tier is not SiteTier.TINY:
        raise ValueError(
            f"mage_residence only supports SiteTier.TINY; got {tier!r}",
        )
    spec = ARCHETYPE_CONFIG["mage_residence"]
    shape_key = rng.choice(MAGE_SHAPE_POOL)
    size = rng.randint(*MAGE_SIZE_RANGE)
    # Circles bias toward EVEN diameter -- the rim curves
    # inward at the equator on even diameters, so partition
    # walls meet the curved exterior on the inner rim rather
    # than the corner-most equator tiles. Octagons keep the
    # historical odd-diameter convention.
    if shape_key == "circle":
        if size % 2 == 1:
            size += 1
    else:
        if size % 2 == 0:
            size += 1
    base_rect = Rect(1, 1, size, size)
    base_shape: RoomShape = (
        OctagonShape() if shape_key == "octagon" else CircleShape()
    )

    n_floors = rng.randint(*MAGE_FLOOR_COUNT_RANGE)
    descent: DungeonRef | None = None
    if rng.random() < MAGE_DESCENT_PROBABILITY:
        descent = DungeonRef(template=MAGE_DESCENT_TEMPLATE)

    building_id = f"{site_id}_mage"
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: build_building_floor(
            building_id=building_id,
            floor_idx=idx,
            base_shape=base_shape,
            base_rect=base_rect,
            n_floors=n,
            rng=rng,
            archetype="mage_residence",
            tags=["mage_residence"],
            required_walkable=req,
        ),
    )

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="stone",
        interior_floor="stone",
        interior_wall_material=spec.interior_wall_material,
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
        kind="mage_residence",
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
    return site


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    """Stamp one ground-floor perimeter tile as ``door_closed``."""
    ground = building.ground
    perim = building.shared_perimeter()
    candidates: list[tuple[int, int]] = []
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        # Reject chamfer steps -- octagon and circle residences
        # put diagonal masonry across these tiles, so a tile-
        # aligned door reads ambiguously (two perpendicular sides
        # face exterior walls drawn diagonally).
        if is_clipped_corner_tile(building, px, py):
            continue
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

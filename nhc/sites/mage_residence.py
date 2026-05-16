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
    CircleShape, Level, OctagonShape, Rect, RoomShape,
    SurfaceType, Terrain, Tile,
)
from nhc.sites._site import (
    Site, is_clipped_corner_tile, outside_neighbour,
    paint_surface_doors, stamp_building_door,
)
from nhc.sites._types import SiteTier
from nhc.hexcrawl.model import DungeonRef


MAGE_SIZE_RANGE = (9, 13)
MAGE_FLOOR_COUNT_RANGE = (2, 4)
MAGE_DESCENT_PROBABILITY = 0.4
MAGE_DESCENT_TEMPLATE = "procedural:crypt"
MAGE_SHAPE_POOL = ("octagon", "circle")

# Tiles of manicured GARDEN periphery on every side of the
# footprint. Generous so the formal-garden geometry has room to
# read in the macro view. The 1-tile VOID margin (per
# ``design/level_surface_layout.md``) is preserved by the surface
# builder skipping the outermost row / column.
MAGE_SURFACE_PADDING = 7
# Trees are planted on a regular lattice centred on the surface
# (every Nth tile both axes) — a kept orchard/allée look, never a
# random scatter. The bush hedge traces the playable border ring.
MAGE_GARDEN_TREE_SPACING = 3


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
    # Centre the residence in a padded canvas so a formal garden
    # rings the footprint on every side. The outermost row /
    # column stays VOID for the 1-tile margin contract per
    # ``design/level_surface_layout.md``.
    pad = MAGE_SURFACE_PADDING
    base_rect = Rect(pad, pad, size, size)
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
        roof_material="tile",
    )
    building.stair_links = stair_links
    door_xy = _place_entry_door(building, rng)
    building.validate()

    surface = _build_mage_garden_surface(
        f"{site_id}_surface", building,
        base_rect.x + base_rect.width + pad,
        base_rect.y + base_rect.height + pad,
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
    _plant_mage_garden(site)
    paint_surface_doors(site, SurfaceType.GARDEN)
    return site


def _build_mage_garden_surface(
    surface_id: str, building: Building, width: int, height: int,
) -> Level:
    """Paint the manicured garden ring around the footprint.

    The footprint stays VOID (the building renderer owns it) and
    the outermost row / column stays VOID for the 1-tile margin
    contract; every other tile becomes GRASS+GARDEN so the hedge
    and the tree lattice have somewhere to land.
    """
    surface = Level.create_empty(
        surface_id, surface_id, 0, width, height,
    )
    surface.metadata.theme = "mage_residence"
    surface.metadata.prerevealed = True

    blocked = set(
        building.base_shape.floor_tiles(building.base_rect),
    )
    for y in range(1, surface.height - 1):
        for x in range(1, surface.width - 1):
            if (x, y) in blocked:
                continue
            surface.tiles[y][x] = Tile(
                terrain=Terrain.GRASS,
                surface_type=SurfaceType.GARDEN,
            )
    return surface


def _plant_mage_garden(site: Site) -> None:
    """Lay out a well-kept formal garden — deterministic, not a
    random scatter.

    * A continuous ``bush`` hedge traces the playable border ring
      (just inside the 1-tile VOID margin).
    * ``tree`` specimens sit on a regular lattice centred on the
      surface (``MAGE_GARDEN_TREE_SPACING`` apart on both axes),
      kept one tile clear of the building so canopies never bleed
      onto the wall / roof.
    * A 1-wide path is cleared from the door straight out to the
      border, with a matching gap (gate) cut in the hedge.
    """
    surface = site.surface
    w, h = surface.width, surface.height
    building = site.buildings[0]
    footprint = set(
        building.base_shape.floor_tiles(building.base_rect),
    )
    # Footprint + its 4-neighbours: keep tree canopies off the
    # walls and roof overhang.
    halo: set[tuple[int, int]] = set(footprint)
    for (fx, fy) in footprint:
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            halo.add((fx + dx, fy + dy))

    r = building.base_rect
    cxb = r.x + r.width / 2.0
    cyb = r.y + r.height / 2.0

    # Straight kept path from each door out to the nearest border.
    path: set[tuple[int, int]] = set()
    for (sx, sy) in site.building_doors:
        ddx = sx - cxb
        ddy = sy - cyb
        if abs(ddx) >= abs(ddy):
            step = (1 if ddx >= 0 else -1, 0)
        else:
            step = (0, 1 if ddy >= 0 else -1)
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
            on_border = x in (1, w - 2) or y in (1, h - 2)
            if on_border and _plantable(x, y):
                surface.tiles[y][x].feature = "bush"

    # Tree lattice, centred so it is mirror-symmetric; the border
    # ring is left to the hedge.
    cx, cy = w // 2, h // 2
    sp = MAGE_GARDEN_TREE_SPACING
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            if (x - cx) % sp or (y - cy) % sp:
                continue
            if (x, y) in halo:
                continue
            if _plantable(x, y):
                surface.tiles[y][x].feature = "tree"


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

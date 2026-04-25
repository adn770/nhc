"""Mansion site assembler.

See ``design/building_generator.md`` section 5.3. A mansion is
2-4 adjacent buildings sharing walls, interconnected by interior
doors on the shared edges. Interior is stone on the ground floor
and wood on upper floors. No enclosure; gardens wrap the compound.
Each building independently rolls a ~20% descent chance.
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
    Level, LShape, OctagonShape, Rect, RectShape, RoomShape,
    SurfaceType, Terrain, Tile,
)
from nhc.sites._site import (
    InteriorDoorLink, Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.sites._types import SiteTier
from nhc.hexcrawl.model import DungeonRef


# ── Mansion tunable constants ────────────────────────────────

# Per-kind tier table. M6b only supports the default tier
# (MEDIUM); future tiers grow when gameplay calls for it.
MANSION_DIMS_BY_TIER: dict[SiteTier, tuple[int, int]] = {
    SiteTier.MEDIUM: (40, 18),
}

MANSION_SURFACE_WIDTH = MANSION_DIMS_BY_TIER[SiteTier.MEDIUM][0]
MANSION_SURFACE_HEIGHT = MANSION_DIMS_BY_TIER[SiteTier.MEDIUM][1]
MANSION_BUILDING_COUNT_RANGE = (2, 4)
MANSION_BUILDING_WIDTH_RANGE = (6, 8)
MANSION_BUILDING_HEIGHT = 7
MANSION_BUILDING_Y = 4
MANSION_BUILDING_X_START = 3
MANSION_FLOOR_COUNT_RANGE = (1, 2)
MANSION_DESCENT_PROBABILITY = 0.2
MANSION_DESCENT_TEMPLATE = "procedural:crypt"
MANSION_SHAPE_POOL = ("rect", "lshape")

# Mage-variant tower tunables (only used when mage_variant=True).
MAGE_TOWER_SIZE = 7
MAGE_TOWER_FLOOR_COUNT_RANGE = (2, 3)
MAGE_TOWER_GAP = 2  # tiles of garden between mansion and tower


def assemble_mansion(
    site_id: str, rng: random.Random,
    mage_variant: bool = False,
    *, tier: SiteTier = SiteTier.MEDIUM,
) -> Site:
    """Assemble a mansion site.

    ``tier`` is accepted for the unified ``Game.enter_site``
    dispatcher API (M6b). Today only ``MEDIUM`` is supported.

    When ``mage_variant`` is True, after the ordinary 2-4 mansion
    buildings are placed an extra octagonal tower building is
    appended on the east side, reached via its own surface entry
    door and carrying teleporter pads on each interior floor — the
    resident mage's workshop.
    """
    if tier is not SiteTier.MEDIUM:
        raise ValueError(
            f"mansion only supports SiteTier.MEDIUM; got {tier!r}",
        )
    n_buildings = rng.randint(*MANSION_BUILDING_COUNT_RANGE)
    buildings: list[Building] = []
    x_cursor = MANSION_BUILDING_X_START
    for i in range(n_buildings):
        w = rng.randint(*MANSION_BUILDING_WIDTH_RANGE)
        rect = Rect(
            x_cursor, MANSION_BUILDING_Y,
            w, MANSION_BUILDING_HEIGHT,
        )
        shape = _pick_shape(rng)
        n_floors = rng.randint(*MANSION_FLOOR_COUNT_RANGE)
        descent: DungeonRef | None = None
        if rng.random() < MANSION_DESCENT_PROBABILITY:
            descent = DungeonRef(template=MANSION_DESCENT_TEMPLATE)
        building = _build_mansion_building(
            f"{site_id}_b{i}", shape, rect, n_floors, descent, rng,
        )
        buildings.append(building)
        x_cursor += w

    mage_tower: Building | None = None
    if mage_variant:
        mage_tower = _build_mage_tower(
            f"{site_id}_mage", x_cursor + MAGE_TOWER_GAP, rng,
        )
        buildings.append(mage_tower)

    # Each building gets at least one exterior entry door.
    combined_footprints: set[tuple[int, int]] = set()
    for b in buildings:
        combined_footprints |= b.base_shape.floor_tiles(b.base_rect)
    entry_doors: dict[
        tuple[int, int], tuple[str, int, int]
    ] = {}
    for b in buildings:
        own = b.base_shape.floor_tiles(b.base_rect)
        door_xy = _place_entry_door(
            b, rng, blocked=combined_footprints - own,
        )
        if door_xy is not None:
            neighbour = outside_neighbour(b, *door_xy)
            if neighbour is not None:
                entry_doors[neighbour] = (
                    b.id, door_xy[0], door_xy[1],
                )

    # Adjacent pairs get a shared interior door at a mid-height tile
    # on both their shared edges.
    interior_doors: dict[
        tuple[str, int, int], tuple[str, int, int]
    ] = {}
    interior_door_links: list[InteriorDoorLink] = []
    for i in range(n_buildings - 1):
        pair = _connect_adjacent_buildings(
            buildings[i], buildings[i + 1],
        )
        if pair is not None:
            (l_id, lx, ly), (r_id, rx, ry) = pair
            interior_doors[(l_id, lx, ly)] = (r_id, rx, ry)
            interior_doors[(r_id, rx, ry)] = (l_id, lx, ly)
            interior_door_links.append(InteriorDoorLink(
                from_building=l_id, to_building=r_id,
                floor=0,
                from_tile=(lx, ly), to_tile=(rx, ry),
            ))

    for b in buildings:
        b.validate()

    surface = _build_mansion_surface(
        f"{site_id}_surface", buildings,
    )

    site = Site(
        id=site_id,
        kind="mansion",
        buildings=buildings,
        surface=surface,
        enclosure=None,
    )
    site.building_doors.update(entry_doors)
    site.interior_doors.update(interior_doors)
    site.interior_door_links.extend(interior_door_links)
    paint_surface_doors(site, SurfaceType.GARDEN)
    if mage_tower is not None:
        _stamp_mage_teleporters(mage_tower, rng)
    return site


def _build_mage_tower(
    building_id: str, x: int, rng: random.Random,
) -> Building:
    """Build the small octagonal tower attached to a mage mansion.

    Uses the ``tower_circle`` archetype (the octagon-compatible
    single-room partitioner) and the ground-floor-stone /
    upper-wood material convention inherited from the mansion.
    """
    size = MAGE_TOWER_SIZE
    rect = Rect(x, MANSION_BUILDING_Y, size, size)
    base_shape = OctagonShape()
    n_floors = rng.randint(*MAGE_TOWER_FLOOR_COUNT_RANGE)
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=rect,
        n_floors=n_floors,
        descent=None,
        rng=rng,
        build_floor_fn=lambda idx, n, req: build_building_floor(
            building_id=building_id,
            floor_idx=idx,
            base_shape=base_shape,
            base_rect=rect,
            n_floors=n,
            rng=rng,
            archetype="tower_circle",
            tags=["mansion_interior", "mage_tower"],
            required_walkable=req,
        ),
    )
    for idx, level in enumerate(floors):
        level.interior_floor = "stone" if idx == 0 else "wood"
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=rect,
        floors=floors,
        descent=None,
        wall_material="stone",
        interior_floor="stone",
        interior_wall_material=(
            ARCHETYPE_CONFIG["tower_circle"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _stamp_mage_teleporters(
    building: Building, rng: random.Random,
) -> None:
    """Stamp one teleporter pair on each floor of the mage tower.

    Mirrors ``nhc.sites.tower._stamp_mage_teleporters`` —
    inlined here to keep the mansion assembler self-contained
    without reaching across site-kind modules.
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


def _pick_shape(rng: random.Random) -> RoomShape:
    key = rng.choice(MANSION_SHAPE_POOL)
    if key == "rect":
        return RectShape()
    return LShape(corner=rng.choice(LShape._VALID_CORNERS))


def _build_mansion_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    rng: random.Random,
) -> Building:
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_mansion_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            required_walkable=req,
        ),
    )
    # Ground stone, upper wood.
    for idx, level in enumerate(floors):
        level.interior_floor = "stone" if idx == 0 else "wood"

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="stone",
        interior_floor="stone",
        interior_wall_material=(
            ARCHETYPE_CONFIG["mansion"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _build_mansion_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    return build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype="mansion",
        tags=["mansion_interior"],
        required_walkable=required_walkable,
    )


def _place_entry_door(
    building: Building, rng: random.Random,
    blocked: set[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    """Pick a perimeter tile to stamp as the entry door.

    ``blocked`` carries the combined footprints of every other
    building in the site; candidates whose outside-neighbour
    falls inside ``blocked`` are rejected so the surface door
    never lands inside a neighbour's wall.
    """
    blocked = blocked or set()
    ground = building.ground
    perim = building.shared_perimeter()
    candidates: list[tuple[int, int]] = []
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        has_wall = False
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if not ground.in_bounds(nx, ny):
                continue
            if ground.tiles[ny][nx].terrain == Terrain.WALL:
                has_wall = True
                break
        if not has_wall:
            continue
        nb = outside_neighbour(building, px, py)
        if nb is None or nb in blocked:
            continue
        candidates.append((px, py))
    if not candidates:
        return None
    dx, dy = rng.choice(sorted(candidates))
    stamp_building_door(building, dx, dy)
    return (dx, dy)


def _connect_adjacent_buildings(
    left: Building, right: Building,
) -> tuple[
    tuple[str, int, int], tuple[str, int, int]
] | None:
    """Place an interior door on each side of the shared wall.

    Buildings are laid out left-to-right with touching bases, so
    ``left.base_rect`` ends at ``x = left.base_rect.x2`` and
    ``right.base_rect`` starts at the next tile. The interior door
    goes on the east edge of left and the west edge of right at a
    y-coord where both perimeters overlap.

    Returns ``((left.id, lx, y), (right.id, rx, y))`` for the
    placed door pair, or ``None`` when the buildings share no
    overlapping perimeter rows.
    """
    left_perim = left.base_shape.perimeter_tiles(left.base_rect)
    right_perim = right.base_shape.perimeter_tiles(right.base_rect)
    left_east = {
        (x, y) for (x, y) in left_perim
        if x == left.base_rect.x2 - 1
    }
    right_west = {
        (x, y) for (x, y) in right_perim
        if x == right.base_rect.x
    }
    overlap_y = sorted(
        {y for (_, y) in left_east}
        & {y for (_, y) in right_west}
    )
    if not overlap_y:
        return None
    y = overlap_y[len(overlap_y) // 2]
    lx = left.base_rect.x2 - 1
    rx = right.base_rect.x
    stamp_building_door(left, lx, y)
    stamp_building_door(right, rx, y)
    return ((left.id, lx, y), (right.id, rx, y))


def _build_mansion_surface(
    surface_id: str, buildings: list[Building],
) -> Level:
    # Fit every building's footprint plus a small garden margin.
    # The default dims are the minimum floor; if the mage variant
    # extends the east side with an octagonal tower, the surface
    # grows to cover it.
    max_x2 = max(
        (b.base_rect.x2 for b in buildings),
        default=MANSION_SURFACE_WIDTH,
    )
    max_y2 = max(
        (b.base_rect.y2 for b in buildings),
        default=MANSION_SURFACE_HEIGHT,
    )
    width = max(MANSION_SURFACE_WIDTH, max_x2 + MANSION_BUILDING_X_START)
    height = max(MANSION_SURFACE_HEIGHT, max_y2 + 3)
    surface = Level.create_empty(
        surface_id, surface_id, 0, width, height,
    )
    # Only building footprints block the garden surface -- no
    # 1-tile buffer ring. The SVG wall mask provides the visual
    # separation, and a ring would seal L-inner-corner doors.
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)

    # Every outdoor tile is garden. Mansions sit on continuous
    # manicured grounds -- buildings are the only non-garden
    # surface.
    for y in range(surface.height):
        for x in range(surface.width):
            if (x, y) in blocked:
                continue
            surface.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.GARDEN,
            )
    return surface

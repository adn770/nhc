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
    place_cross_floor_stairs,
)
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.single_room import SingleRoomPartitioner
from nhc.dungeon.model import (
    Level, LShape, Rect, RectShape, RoomShape, SurfaceType,
    Terrain, Tile,
)
from nhc.dungeon.site import (
    Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.hexcrawl.model import DungeonRef


# ── Mansion tunable constants ────────────────────────────────

MANSION_SURFACE_WIDTH = 40
MANSION_SURFACE_HEIGHT = 18
MANSION_BUILDING_COUNT_RANGE = (2, 4)
MANSION_BUILDING_WIDTH_RANGE = (6, 8)
MANSION_BUILDING_HEIGHT = 7
MANSION_BUILDING_Y = 4
MANSION_BUILDING_X_START = 3
MANSION_FLOOR_COUNT_RANGE = (1, 2)
MANSION_DESCENT_PROBABILITY = 0.2
MANSION_DESCENT_TEMPLATE = "procedural:crypt"
MANSION_SHAPE_POOL = ("rect", "lshape")


def assemble_mansion(
    site_id: str, rng: random.Random,
) -> Site:
    """Assemble a mansion site."""
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
    for i in range(n_buildings - 1):
        pair = _connect_adjacent_buildings(
            buildings[i], buildings[i + 1],
        )
        if pair is not None:
            (l_id, lx, ly), (r_id, rx, ry) = pair
            interior_doors[(l_id, lx, ly)] = (r_id, rx, ry)
            interior_doors[(r_id, rx, ry)] = (l_id, lx, ly)

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
    paint_surface_doors(site, SurfaceType.GARDEN)
    return site


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
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_mansion_floor(
            building_id, idx, base_shape, base_rect, n_floors, rng,
        )
        # Ground stone, upper wood.
        if idx == 0:
            level.interior_floor = "stone"
        else:
            level.interior_floor = "wood"
        floors.append(level)

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="stone",
        interior_floor="stone",
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    return building


def _build_mansion_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
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
        partitioner=SingleRoomPartitioner(),
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
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        MANSION_SURFACE_WIDTH, MANSION_SURFACE_HEIGHT,
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

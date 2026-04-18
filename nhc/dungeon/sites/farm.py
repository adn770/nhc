"""Farm site assembler.

See ``design/building_generator.md`` section 5.2. A farm is 1-2
small wood-interior buildings (farmhouse + optional barn)
surrounded by a large FIELD region, with a few GARDEN tiles in a
ring around the farmhouse. No enclosure. Rare descent (~10%,
farmhouse only).
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import place_cross_floor_stairs
from nhc.dungeon.model import (
    Level, LShape, Rect, RectShape, Room, RoomShape, SurfaceType,
    Terrain, Tile,
)
from nhc.dungeon.site import Site
from nhc.hexcrawl.model import DungeonRef


# ── Farm tunable constants ───────────────────────────────────

FARM_SURFACE_WIDTH = 30
FARM_SURFACE_HEIGHT = 22
FARM_FARMHOUSE_POS = (5, 4)
FARM_FARMHOUSE_SIZE = (8, 7)
FARM_BARN_POS = (18, 10)
FARM_BARN_SIZE = (6, 6)
FARM_FLOOR_COUNT_RANGE = (1, 2)
FARM_BARN_PROBABILITY = 0.5
FARM_DESCENT_PROBABILITY = 0.1
FARM_DESCENT_TEMPLATE = "procedural:crypt"
FARM_GARDEN_RING = 1  # tiles of garden around farmhouse perimeter
FARM_SHAPE_POOL = ("rect", "lshape")


def assemble_farm(
    site_id: str, rng: random.Random,
) -> Site:
    """Assemble a farm site.

    Returns a :class:`Site` with one farmhouse building and an
    optional barn, a FIELD-dominated surface level, and a
    GARDEN ring around the farmhouse. No enclosure.
    """
    farmhouse_rect = Rect(
        FARM_FARMHOUSE_POS[0], FARM_FARMHOUSE_POS[1],
        FARM_FARMHOUSE_SIZE[0], FARM_FARMHOUSE_SIZE[1],
    )
    farmhouse_shape = _pick_shape(rng)
    farmhouse_floors = rng.randint(*FARM_FLOOR_COUNT_RANGE)
    farmhouse_descent: DungeonRef | None = None
    if rng.random() < FARM_DESCENT_PROBABILITY:
        farmhouse_descent = DungeonRef(template=FARM_DESCENT_TEMPLATE)
    farmhouse = _build_farm_building(
        f"{site_id}_farmhouse", farmhouse_shape, farmhouse_rect,
        farmhouse_floors, descent=farmhouse_descent, rng=rng,
    )

    buildings = [farmhouse]
    if rng.random() < FARM_BARN_PROBABILITY:
        barn_rect = Rect(
            FARM_BARN_POS[0], FARM_BARN_POS[1],
            FARM_BARN_SIZE[0], FARM_BARN_SIZE[1],
        )
        barn_shape = RectShape()  # barns are always rect
        barn_floors = rng.randint(1, 2)
        barn = _build_farm_building(
            f"{site_id}_barn", barn_shape, barn_rect,
            barn_floors, descent=None, rng=rng,
        )
        buildings.append(barn)

    surface = _build_farm_surface(
        f"{site_id}_surface", buildings, farmhouse,
    )

    return Site(
        id=site_id,
        kind="farm",
        buildings=buildings,
        surface=surface,
        enclosure=None,
    )


def _pick_shape(rng: random.Random) -> RoomShape:
    key = rng.choice(FARM_SHAPE_POOL)
    if key == "rect":
        return RectShape()
    return LShape(corner=rng.choice(LShape._VALID_CORNERS))


def _build_farm_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    rng: random.Random,
) -> Building:
    floors: list[Level] = []
    for idx in range(n_floors):
        floors.append(
            _build_farm_floor(building_id, idx, base_shape, base_rect)
        )
    # Farms are wood throughout.
    for f in floors:
        f.interior_floor = "wood"
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="brick",
        interior_floor="wood",
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    _place_entry_door(building, rng)
    building.validate()
    return building


def _build_farm_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
) -> Level:
    w = base_rect.x + base_rect.width + 2
    h = base_rect.y + base_rect.height + 2
    level = Level.create_empty(
        f"{building_id}_f{floor_idx}",
        f"{building_id} floor {floor_idx}",
        floor_idx + 1, w, h,
    )
    footprint = base_shape.floor_tiles(base_rect)
    for (x, y) in footprint:
        level.tiles[y][x] = Tile(terrain=Terrain.FLOOR)
    for (x, y) in footprint:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = x + dx, y + dy
                if (nx, ny) in footprint:
                    continue
                if not level.in_bounds(nx, ny):
                    continue
                if level.tiles[ny][nx].terrain == Terrain.VOID:
                    level.tiles[ny][nx] = Tile(terrain=Terrain.WALL)
    level.rooms = [Room(
        id=f"{building_id}_f{floor_idx}_room",
        rect=Rect(
            base_rect.x, base_rect.y,
            base_rect.width, base_rect.height,
        ),
        shape=base_shape,
        tags=["farm_interior"] + (
            ["entrance"] if floor_idx == 0 else []
        ),
    )]
    level.building_id = building_id
    level.floor_index = floor_idx
    level.interior_floor = "wood"
    return level


def _place_entry_door(
    building: Building, rng: random.Random,
) -> None:
    ground = building.ground
    perim = building.shared_perimeter()
    candidates: list[tuple[int, int]] = []
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if not ground.in_bounds(nx, ny):
                continue
            if ground.tiles[ny][nx].terrain == Terrain.WALL:
                candidates.append((px, py))
                break
    if not candidates:
        return
    dx, dy = rng.choice(sorted(candidates))
    ground.tiles[dy][dx].feature = "door_closed"


def _build_farm_surface(
    surface_id: str, buildings: list[Building],
    farmhouse: Building,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        FARM_SURFACE_WIDTH, FARM_SURFACE_HEIGHT,
    )
    # Collect all footprint tiles across buildings.
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)
        # Also block the wall ring immediately around each building
        # so fields don't paint over them.
        for (x, y) in b.base_shape.floor_tiles(b.base_rect):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    blocked.add((x + dx, y + dy))

    # Garden ring around the farmhouse (one tile beyond the ring
    # blocked above).
    farmhouse_footprint = farmhouse.base_shape.floor_tiles(
        farmhouse.base_rect,
    )
    garden_tiles: set[tuple[int, int]] = set()
    for (x, y) in farmhouse_footprint:
        for dx in range(-FARM_GARDEN_RING - 1,
                        FARM_GARDEN_RING + 2):
            for dy in range(-FARM_GARDEN_RING - 1,
                            FARM_GARDEN_RING + 2):
                ax, ay = x + dx, y + dy
                if (ax, ay) in blocked:
                    continue
                if not surface.in_bounds(ax, ay):
                    continue
                dist = max(abs(dx), abs(dy))
                if dist == FARM_GARDEN_RING + 1:
                    garden_tiles.add((ax, ay))

    # Fill surface: FIELD everywhere open, GARDEN in the ring.
    for y in range(surface.height):
        for x in range(surface.width):
            if (x, y) in blocked:
                continue
            tile = Tile(terrain=Terrain.FLOOR)
            if (x, y) in garden_tiles:
                tile.surface_type = SurfaceType.GARDEN
            else:
                tile.surface_type = SurfaceType.FIELD
            surface.tiles[y][x] = tile
    return surface

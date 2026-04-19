"""Keep site assembler.

See ``design/building_generator.md`` section 5.4. A keep is a
fortified compound: 2-3 main buildings (rect or octagonal, 1-2
floors) plus 2-4 smaller sparse buildings (armoury, smithy,
storehouse) arranged around the courtyard. A fortification wall
wraps the whole compound with 1-2 gates. Surface inside the wall
is STREET; interior floors are stone throughout; descent chance
on main buildings is ~40%.

Supersedes the old single-level ``procedural:keep`` template (the
original template still exists elsewhere and will be removed in a
later cleanup milestone).
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import place_cross_floor_stairs
from nhc.dungeon.model import (
    Level, OctagonShape, Rect, RectShape, Room, RoomShape,
    SurfaceType, Terrain, Tile,
)
from nhc.dungeon.site import Enclosure, Site
from nhc.hexcrawl.model import DungeonRef


# ── Keep tunable constants ───────────────────────────────────

KEEP_SURFACE_WIDTH = 46
KEEP_SURFACE_HEIGHT = 36

KEEP_MAIN_BUILDING_COUNT_RANGE = (2, 3)
KEEP_MAIN_BUILDING_WIDTH_RANGE = (7, 9)
KEEP_MAIN_BUILDING_HEIGHT = 9
KEEP_MAIN_BUILDING_Y = 6
KEEP_MAIN_BUILDING_X_START = 6
KEEP_MAIN_FLOOR_COUNT_RANGE = (1, 2)

KEEP_SPARSE_BUILDING_COUNT_RANGE = (2, 4)
KEEP_SPARSE_SIZE_RANGE = (3, 5)

KEEP_DESCENT_PROBABILITY = 0.4
KEEP_DESCENT_TEMPLATE = "procedural:crypt"

KEEP_FORTIFICATION_PADDING = 4       # tiles beyond bbox for wall
KEEP_GATE_COUNT_RANGE = (1, 2)
KEEP_GATE_LENGTH_TILES = 3

KEEP_MAIN_SHAPE_POOL = ("rect", "octagon")
KEEP_SPARSE_SHAPE = "rect"           # sparse = always small rect


def assemble_keep(
    site_id: str, rng: random.Random,
) -> Site:
    """Assemble a keep site."""
    main_count = rng.randint(*KEEP_MAIN_BUILDING_COUNT_RANGE)
    sparse_count = rng.randint(*KEEP_SPARSE_BUILDING_COUNT_RANGE)

    main_buildings: list[Building] = []
    x_cursor = KEEP_MAIN_BUILDING_X_START
    for i in range(main_count):
        w = rng.randint(*KEEP_MAIN_BUILDING_WIDTH_RANGE)
        rect = Rect(
            x_cursor, KEEP_MAIN_BUILDING_Y,
            w, KEEP_MAIN_BUILDING_HEIGHT,
        )
        shape = _pick_main_shape(rng)
        n_floors = rng.randint(*KEEP_MAIN_FLOOR_COUNT_RANGE)
        descent: DungeonRef | None = None
        if rng.random() < KEEP_DESCENT_PROBABILITY:
            descent = DungeonRef(template=KEEP_DESCENT_TEMPLATE)
        building = _build_keep_building(
            f"{site_id}_keep_main_b{i}", shape, rect,
            n_floors, descent, rng,
        )
        main_buildings.append(building)
        x_cursor += w

    # Place sparse buildings in a row below the main compound.
    sparse_buildings: list[Building] = []
    sparse_y = (
        KEEP_MAIN_BUILDING_Y + KEEP_MAIN_BUILDING_HEIGHT + 4
    )
    sx_cursor = KEEP_MAIN_BUILDING_X_START
    for i in range(sparse_count):
        sw = rng.randint(*KEEP_SPARSE_SIZE_RANGE)
        sh = rng.randint(*KEEP_SPARSE_SIZE_RANGE)
        rect = Rect(sx_cursor, sparse_y, sw, sh)
        building = _build_keep_building(
            f"{site_id}_keep_sparse_b{i}", RectShape(), rect,
            1, None, rng,
        )
        sparse_buildings.append(building)
        sx_cursor += sw + 2

    buildings = main_buildings + sparse_buildings
    door_map: dict[tuple[int, int], str] = {}
    for b in buildings:
        door_xy = _place_entry_door(b, rng)
        if door_xy is not None:
            door_map[door_xy] = b.id
        b.validate()

    enclosure = _build_fortification(buildings, rng)
    surface = _build_keep_surface(
        f"{site_id}_surface", buildings, enclosure,
    )

    site = Site(
        id=site_id,
        kind="keep",
        buildings=buildings,
        surface=surface,
        enclosure=enclosure,
    )
    site.building_doors.update(door_map)
    return site


def _pick_main_shape(rng: random.Random) -> RoomShape:
    key = rng.choice(KEEP_MAIN_SHAPE_POOL)
    if key == "rect":
        return RectShape()
    return OctagonShape()


def _build_keep_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    rng: random.Random,
) -> Building:
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_keep_floor(
            building_id, idx, base_shape, base_rect,
        )
        level.interior_floor = "stone"
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


def _build_keep_floor(
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
        tags=["keep_interior"] + (
            ["entrance"] if floor_idx == 0 else []
        ),
    )]
    level.building_id = building_id
    level.floor_index = floor_idx
    return level


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
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
        return None
    dx, dy = rng.choice(sorted(candidates))
    ground.tiles[dy][dx].feature = "door_closed"
    return (dx, dy)


def _build_fortification(
    buildings: list[Building], rng: random.Random,
) -> Enclosure:
    """Axis-aligned fortification polygon around every building."""
    xs: list[int] = []
    ys: list[int] = []
    for b in buildings:
        xs.extend([b.base_rect.x, b.base_rect.x2])
        ys.extend([b.base_rect.y, b.base_rect.y2])
    pad = KEEP_FORTIFICATION_PADDING
    min_x = min(xs) - pad
    max_x = max(xs) + pad
    min_y = min(ys) - pad
    max_y = max(ys) + pad
    polygon = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    ]

    gate_count = rng.randint(*KEEP_GATE_COUNT_RANGE)
    # Gates are placed as (edge_midpoint_x, edge_midpoint_y, length)
    # tuples; choose one or two polygon edges at random.
    edges = list(range(4))
    rng.shuffle(edges)
    gates: list[tuple[int, int, int]] = []
    for i in range(gate_count):
        edge_idx = edges[i]
        a = polygon[edge_idx]
        b = polygon[(edge_idx + 1) % 4]
        mx = (a[0] + b[0]) // 2
        my = (a[1] + b[1]) // 2
        gates.append((mx, my, KEEP_GATE_LENGTH_TILES))

    return Enclosure(
        kind="fortification",
        polygon=polygon,
        gates=gates,
    )


def _build_keep_surface(
    surface_id: str, buildings: list[Building],
    enclosure: Enclosure,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        KEEP_SURFACE_WIDTH, KEEP_SURFACE_HEIGHT,
    )
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)
        for (x, y) in b.base_shape.floor_tiles(b.base_rect):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    blocked.add((x + dx, y + dy))

    xs = [p[0] for p in enclosure.polygon]
    ys = [p[1] for p in enclosure.polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Fortification polygon vertices align with tile boundaries;
    # tile (tx, ty) is inside the polygon only when tx+1 <= max_x
    # and ty+1 <= max_y, so STREET fill stops one row short of
    # max_x / max_y so the wall reads as enclosing the courtyard
    # instead of cutting through one tile of it.
    for y in range(max(0, min_y), min(surface.height, max_y)):
        for x in range(max(0, min_x), min(surface.width, max_x)):
            if (x, y) in blocked:
                continue
            tile = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
            surface.tiles[y][x] = tile
    return surface

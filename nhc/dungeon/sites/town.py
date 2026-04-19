"""Town site assembler.

See ``design/building_generator.md`` section 5.5. A town is 5-8
small buildings placed in a 2-row grid, surrounded by a palisade
enclosure with 1-2 gates, with STREET surface between buildings.
Interiors mix wood (residential / market) and stone
(temple / garrison). Descent is rare.

Supersedes the old single-level ``SettlementGenerator`` single-
level output (the original generator is left in place; this
assembler returns a richer Site with Building instances).
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import place_cross_floor_stairs
from nhc.dungeon.model import (
    Level, LShape, Rect, RectShape, Room, RoomShape, SurfaceType,
    Terrain, Tile,
)
from nhc.dungeon.site import Enclosure, Site
from nhc.hexcrawl.model import DungeonRef


# ── Town tunable constants ───────────────────────────────────

TOWN_SURFACE_WIDTH = 50
TOWN_SURFACE_HEIGHT = 30
TOWN_BUILDING_COUNT_RANGE = (5, 8)
TOWN_BUILDING_SIZE_RANGE = (5, 7)     # min 5 guarantees L-shape
                                      # has interior for stairs
TOWN_ROW_Y = (6, 17)
TOWN_ROW_X_START = 6
TOWN_BUILDING_SPACING = 3                 # tile gap between buildings
TOWN_FLOOR_COUNT_RANGE = (1, 2)

TOWN_WOOD_BUILDING_PROBABILITY = 0.65    # rest are stone
TOWN_DESCENT_PROBABILITY = 0.08
TOWN_DESCENT_TEMPLATE = "procedural:crypt"

TOWN_PALISADE_PADDING = 3                # tiles beyond bbox
TOWN_GATE_COUNT_RANGE = (1, 2)
TOWN_GATE_LENGTH_TILES = 2

# Main street runs horizontally in the gap between the two
# building rows. Its y-centre is used to anchor palisade gates
# so the entrances line up with the road running through town.
TOWN_MAIN_STREET_Y = (
    TOWN_ROW_Y[0] + TOWN_BUILDING_SIZE_RANGE[1]
    + (
        TOWN_ROW_Y[1] - TOWN_ROW_Y[0]
        - TOWN_BUILDING_SIZE_RANGE[1]
    ) // 2
)

TOWN_SHAPE_POOL = ("rect", "lshape")


def assemble_town(
    site_id: str, rng: random.Random,
) -> Site:
    """Assemble a town site."""
    n_buildings = rng.randint(*TOWN_BUILDING_COUNT_RANGE)

    # Distribute buildings across two rows.
    per_row = (n_buildings + 1) // 2
    buildings: list[Building] = []
    for row_idx, base_y in enumerate(TOWN_ROW_Y):
        x_cursor = TOWN_ROW_X_START
        for i in range(per_row):
            if len(buildings) >= n_buildings:
                break
            w = rng.randint(*TOWN_BUILDING_SIZE_RANGE)
            h = rng.randint(*TOWN_BUILDING_SIZE_RANGE)
            rect = Rect(x_cursor, base_y, w, h)
            shape = _pick_shape(rng)
            n_floors = rng.randint(*TOWN_FLOOR_COUNT_RANGE)
            is_wood = rng.random() < TOWN_WOOD_BUILDING_PROBABILITY
            interior = "wood" if is_wood else "stone"
            descent: DungeonRef | None = None
            if rng.random() < TOWN_DESCENT_PROBABILITY:
                descent = DungeonRef(template=TOWN_DESCENT_TEMPLATE)
            building = _build_town_building(
                f"{site_id}_b{row_idx}_{i}", shape, rect,
                n_floors, descent, interior, rng,
            )
            buildings.append(building)
            x_cursor += w + TOWN_BUILDING_SPACING

    for b in buildings:
        _place_entry_door(b, rng)
        b.validate()

    enclosure = _build_palisade(buildings, rng)
    surface = _build_town_surface(
        f"{site_id}_surface", buildings, enclosure,
    )

    return Site(
        id=site_id,
        kind="town",
        buildings=buildings,
        surface=surface,
        enclosure=enclosure,
    )


def _pick_shape(rng: random.Random) -> RoomShape:
    key = rng.choice(TOWN_SHAPE_POOL)
    if key == "rect":
        return RectShape()
    return LShape(corner=rng.choice(LShape._VALID_CORNERS))


def _build_town_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    interior: str, rng: random.Random,
) -> Building:
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_town_floor(
            building_id, idx, base_shape, base_rect,
        )
        level.interior_floor = interior
        floors.append(level)
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="brick" if interior == "wood" else "stone",
        interior_floor=interior,
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    return building


def _build_town_floor(
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
        tags=["town_interior"] + (
            ["entrance"] if floor_idx == 0 else []
        ),
    )]
    level.building_id = building_id
    level.floor_index = floor_idx
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


def _build_palisade(
    buildings: list[Building], rng: random.Random,
) -> Enclosure:
    xs: list[int] = []
    ys: list[int] = []
    for b in buildings:
        xs.extend([b.base_rect.x, b.base_rect.x2])
        ys.extend([b.base_rect.y, b.base_rect.y2])
    pad = TOWN_PALISADE_PADDING
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
    # Palisade gates sit on the east / west edges at the main
    # street's y-centre so the road runs straight through the
    # town -- not at random midpoints of a random edge.
    gate_count = rng.randint(*TOWN_GATE_COUNT_RANGE)
    sides = ["west", "east"]
    rng.shuffle(sides)
    gates: list[tuple[int, int, int]] = []
    for i in range(gate_count):
        gx = min_x if sides[i] == "west" else max_x
        gates.append(
            (gx, TOWN_MAIN_STREET_Y, TOWN_GATE_LENGTH_TILES),
        )
    return Enclosure(
        kind="palisade", polygon=polygon, gates=gates,
    )


def _build_town_surface(
    surface_id: str, buildings: list[Building],
    enclosure: Enclosure,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        TOWN_SURFACE_WIDTH, TOWN_SURFACE_HEIGHT,
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

    # Enclosure polygon sits at tile boundaries: vertex (x, y)
    # aligns with the top-left corner of tile (x, y). A tile at
    # (tx, ty) is inside the polygon only when tx+1 <= max_x and
    # ty+1 <= max_y, so the STREET fill stops one row short of
    # max_x / max_y -- otherwise tiles at max_x or max_y would
    # sit outside the palisade and read as "one tile off".
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

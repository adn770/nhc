"""Ruin site assembler.

See ``design/biome_features.md`` §6. A ruin is an abandoned
dungeon entrance: a single partial stone building inside a
broken fortification, no service NPCs, with a mandatory 3-floor
descent attached to the building. The surface is populated with
hostile creatures by the standard ``populate_level`` pipeline so
the player has something to fight on arrival.

All ruin geometry lives as module-level constants
(``RUIN_BUILDING_COUNT_RANGE`` etc.) so tuning is a one-line
edit. Surface ring style differs per biome; every other knob is
shared across the five ruin biomes.

Descent wiring (actually letting the player enter the building
and descend) lands in milestone 7 alongside N-floor descent
support in ``_enter_building_descent``.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    flip_building_stair_semantics, place_cross_floor_stairs,
)
from nhc.dungeon.model import (
    Level, Rect, RectShape, Room, RoomShape, SurfaceType,
    Terrain, Tile,
)
from nhc.dungeon.model import EntityPlacement
from nhc.dungeon.populator import (
    CREATURE_POOLS, ENCOUNTER_GROUPS, FACTION_POOLS,
)
from nhc.dungeon.site import (
    Enclosure, Site, outside_neighbour, paint_surface_doors,
)
from nhc.hexcrawl.model import Biome, DungeonRef


# ── Ruin tunable constants ───────────────────────────────────

RUIN_BUILDING_COUNT_RANGE = (1, 1)     # single partial building
                                       # in v1; bump later without
                                       # logic change.
RUIN_ENCLOSURE_KIND = "fortification"  # stone reads as ancient;
                                       # future: dict[biome, kind]
                                       # for biome-specific styles.
RUIN_DESCENT_FLOORS = 3
RUIN_DESCENT_TEMPLATE = "procedural:ruin"

RUIN_SURFACE_WIDTH = 18
RUIN_SURFACE_HEIGHT = 14
RUIN_BUILDING_POS = (6, 4)
RUIN_BUILDING_SIZE = (7, 6)
RUIN_ENCLOSURE_PADDING = 3
RUIN_GATE_LENGTH_TILES = 2
RUIN_PARTIAL_WALL_DROP_RANGE = (2, 4)


def assemble_ruin(
    site_id: str, rng: random.Random,
    biome: Biome | None = None,
) -> Site:
    """Assemble a ruin site.

    ``biome`` controls only the surface ring flavour:

    - :attr:`Biome.FOREST` gets a GARDEN ring (ivy / moss).
    - :attr:`Biome.MARSH` gets a FIELD ring (waterlogged ground).
    - :attr:`Biome.DEADLANDS` / :attr:`Biome.SANDLANDS` /
      :attr:`Biome.ICELANDS` use bare FLOOR.

    Every biome uses the same layout recipe, enclosure kind,
    descent depth, and faction pool (v1). Only the surface ring
    differs.
    """
    if biome is None:
        biome = Biome.FOREST

    base_rect = Rect(
        RUIN_BUILDING_POS[0], RUIN_BUILDING_POS[1],
        RUIN_BUILDING_SIZE[0], RUIN_BUILDING_SIZE[1],
    )
    shape: RoomShape = RectShape()
    building = _build_ruin_building(
        f"{site_id}_ruin_b0", shape, base_rect, rng,
    )
    _drop_perimeter_walls(building, rng)

    door_xy = _place_entry_door(building, rng)
    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    if door_xy is not None:
        neighbour = outside_neighbour(building, *door_xy)
        if neighbour is not None:
            door_map[neighbour] = (
                building.id, door_xy[0], door_xy[1],
            )
    building.validate()

    buildings = [building]
    enclosure = _build_broken_fortification([building], rng)
    surface = _build_ruin_surface(
        f"{site_id}_surface", buildings, enclosure, biome,
    )

    site = Site(
        id=site_id,
        kind="ruin",
        buildings=buildings,
        surface=surface,
        enclosure=enclosure,
    )
    site.building_doors.update(door_map)
    paint_surface_doors(site, _default_surface_type(biome))

    # Populate the surface with hostile creatures. v1 relies on
    # the standard populator (Caves-of-Chaos humanoid pool);
    # design/biome_features.md §8 plans v2 biome-specific faction
    # pools.
    _populate_ruin_surface(surface, rng)
    return site


def _default_surface_type(biome: Biome) -> SurfaceType:
    if biome is Biome.FOREST:
        return SurfaceType.GARDEN
    if biome is Biome.MARSH:
        return SurfaceType.FIELD
    return SurfaceType.NONE


def _build_ruin_building(
    building_id: str, shape: RoomShape, base_rect: Rect,
    rng: random.Random,
) -> Building:
    """Single-floor stone building with a mandatory descent.

    The descent's :class:`DungeonRef` points every floor at the
    ``procedural:ruin`` template; milestone 7 generalises
    ``_enter_building_descent`` so all three floors are reachable.
    """
    ground = _build_ruin_floor(building_id, 0, shape, base_rect)
    ground.interior_floor = "stone"
    descent = DungeonRef(
        template=RUIN_DESCENT_TEMPLATE,
        depth=RUIN_DESCENT_FLOORS,
    )
    building = Building(
        id=building_id,
        base_shape=shape,
        base_rect=base_rect,
        floors=[ground],
        descent=descent,
        wall_material="stone",
        interior_floor="stone",
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    flip_building_stair_semantics(building)
    return building


def _build_ruin_floor(
    building_id: str, floor_idx: int,
    shape: RoomShape, base_rect: Rect,
) -> Level:
    w = base_rect.x + base_rect.width + 2
    h = base_rect.y + base_rect.height + 2
    level = Level.create_empty(
        f"{building_id}_f{floor_idx}",
        f"{building_id} floor {floor_idx}",
        floor_idx + 1, w, h,
    )
    footprint = shape.floor_tiles(base_rect)
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
        shape=shape,
        tags=["ruin_interior"] + (
            ["entrance"] if floor_idx == 0 else []
        ),
    )]
    level.building_id = building_id
    level.floor_index = floor_idx
    level.interior_floor = "stone"
    return level


def _drop_perimeter_walls(
    building: Building, rng: random.Random,
) -> None:
    """Revert 2-4 perimeter wall tiles to VOID.

    Matches the mysterious-temple recipe so "partial walls" reads
    consistently across the two assemblers. Must run before
    ``_place_entry_door`` so the door never lands on a tile that
    is about to be dropped.
    """
    ground = building.ground
    footprint = building.base_shape.floor_tiles(building.base_rect)
    perimeter: list[tuple[int, int]] = []
    for (x, y) in footprint:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                nx, ny = x + dx, y + dy
                if (nx, ny) in footprint:
                    continue
                if not ground.in_bounds(nx, ny):
                    continue
                if ground.tiles[ny][nx].terrain is Terrain.WALL:
                    perimeter.append((nx, ny))
    perimeter = sorted(set(perimeter))
    if not perimeter:
        return
    lo, hi = RUIN_PARTIAL_WALL_DROP_RANGE
    drop_count = rng.randint(lo, min(hi, len(perimeter)))
    for (x, y) in rng.sample(perimeter, drop_count):
        ground.tiles[y][x] = Tile(terrain=Terrain.VOID)


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    ground = building.ground
    candidates: list[tuple[int, int]] = []
    for (px, py) in building.shared_perimeter():
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = px + dx, py + dy
            if not ground.in_bounds(nx, ny):
                continue
            if ground.tiles[ny][nx].terrain is Terrain.WALL:
                candidates.append((px, py))
                break
    if not candidates:
        return None
    dx, dy = rng.choice(sorted(candidates))
    ground.tiles[dy][dx].feature = "door_closed"
    return (dx, dy)


def _build_broken_fortification(
    buildings: list[Building], rng: random.Random,
) -> Enclosure:
    """Axis-aligned fortification with a single broken gate.

    The enclosure is structurally a regular keep-style
    fortification -- the "broken" aspect is conceptual (gate
    count is fixed at 1, gate length is two tiles, styling lives
    in future surface rendering choices).
    """
    xs: list[int] = []
    ys: list[int] = []
    for b in buildings:
        xs.extend([b.base_rect.x, b.base_rect.x2])
        ys.extend([b.base_rect.y, b.base_rect.y2])
    pad = RUIN_ENCLOSURE_PADDING
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
    edge_idx = rng.randrange(4)
    a = polygon[edge_idx]
    b = polygon[(edge_idx + 1) % 4]
    mx = (a[0] + b[0]) // 2
    my = (a[1] + b[1]) // 2
    gates = [(mx, my, RUIN_GATE_LENGTH_TILES)]
    return Enclosure(
        kind=RUIN_ENCLOSURE_KIND,
        polygon=polygon,
        gates=gates,
    )


def _build_ruin_surface(
    surface_id: str, buildings: list[Building],
    enclosure: Enclosure, biome: Biome,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        RUIN_SURFACE_WIDTH, RUIN_SURFACE_HEIGHT,
    )
    surface.metadata.theme = "ruin"
    surface.metadata.ambient = "ruin"
    surface.metadata.prerevealed = True

    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        footprint = b.base_shape.floor_tiles(b.base_rect)
        blocked |= footprint
        for (x, y) in footprint:
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    blocked.add((x + dx, y + dy))

    xs = [p[0] for p in enclosure.polygon]
    ys = [p[1] for p in enclosure.polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    default_surface = _default_surface_type(biome)
    filled: list[tuple[int, int]] = []
    for y in range(max(0, min_y), min(surface.height, max_y)):
        for x in range(max(0, min_x), min(surface.width, max_x)):
            if (x, y) in blocked:
                continue
            tile = Tile(
                terrain=Terrain.FLOOR,
                surface_type=default_surface,
            )
            surface.tiles[y][x] = tile
            filled.append((x, y))

    # Model the enclosed outdoor area as a single Room so the
    # populator has somewhere to spawn hostile creatures. Uses
    # the inner bounding rect of filled tiles, clamped to at
    # least 3x3 (populator requirement).
    if filled:
        fx = [x for (x, _) in filled]
        fy = [y for (_, y) in filled]
        rect = Rect(
            min(fx), min(fy),
            max(1, max(fx) - min(fx) + 1),
            max(1, max(fy) - min(fy) + 1),
        )
        surface.rooms = [Room(
            id=f"{surface_id}_courtyard",
            rect=rect,
            shape=RectShape(),
            tags=["ruin_surface"],
        )]

    return surface


def _populate_ruin_surface(
    surface: Level, rng: random.Random,
) -> None:
    """Place hostile creatures on the ruin surface.

    Ruins are abandoned, so the full ``populate_level`` pass is
    too generous -- it places a recruitable adventurer on
    depth <= 1 which breaks the "no service NPCs" invariant. We
    reuse the populator's depth-1 creature pool and encounter
    size rules but skip the adventurer, item bury, and trap
    passes. When ``surface.metadata.faction`` is set (biome-
    features v2 wires this via
    :func:`place_features._place_ruins`), the faction's
    :data:`FACTION_POOLS` entry drives the creature roll instead
    of the shared depth-1 pool.
    """
    if not surface.rooms:
        return
    room = surface.rooms[0]
    faction = (
        surface.metadata.faction if surface.metadata else None
    )
    if faction and faction in FACTION_POOLS:
        c_pool = FACTION_POOLS[faction]
    else:
        c_pool = CREATURE_POOLS[1]
    c_ids, c_weights = zip(*c_pool)
    encounter_count = 2 + rng.randint(0, 2)

    occupied: set[tuple[int, int]] = set()
    placed = 0
    max_attempts = encounter_count * 3
    while placed < encounter_count and max_attempts > 0:
        max_attempts -= 1
        _, gmin, gmax = rng.choice(ENCOUNTER_GROUPS)
        size = min(
            rng.randint(gmin, gmax), encounter_count - placed,
        )
        creature_id = rng.choices(
            list(c_ids), weights=list(c_weights), k=1,
        )[0]
        for _ in range(size):
            pos = _pick_surface_tile(surface, room, occupied, rng)
            if pos is None:
                break
            surface.entities.append(EntityPlacement(
                entity_type="creature", entity_id=creature_id,
                x=pos[0], y=pos[1],
            ))
            occupied.add(pos)
            placed += 1


def _pick_surface_tile(
    surface: Level, room: Room,
    occupied: set[tuple[int, int]], rng: random.Random,
) -> tuple[int, int] | None:
    rect = room.rect
    candidates: list[tuple[int, int]] = []
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            tile = surface.tile_at(x, y)
            if tile is None:
                continue
            if tile.terrain is not Terrain.FLOOR:
                continue
            if tile.feature is not None:
                continue
            if (x, y) in occupied:
                continue
            candidates.append((x, y))
    if not candidates:
        return None
    return rng.choice(candidates)

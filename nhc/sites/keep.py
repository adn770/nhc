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
from nhc.dungeon.generators._stairs import (
    build_floors_with_stairs,
)
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.dungeon.model import (
    EntityPlacement, Level, OctagonShape, Rect, RectShape,
    RoomShape, SurfaceType, Terrain, Tile,
)
from nhc.sites._site import (
    Enclosure, Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.hexcrawl.model import DungeonRef


# ── Keep tunable constants ───────────────────────────────────

KEEP_SURFACE_WIDTH = 46
KEEP_SURFACE_HEIGHT = 36

# biome-features v2 M12: the inhabited half of the keep↔ruin pair.
# 2-4 guards scatter across the courtyard; one quartermaster sits
# within GATE_PROXIMITY tiles of the first gate so the player meets
# them on entry; one commander stands near the largest main
# building so they read as the garrison's head.
KEEP_GUARD_COUNT_RANGE = (2, 4)
KEEP_QUARTERMASTER_GATE_PROXIMITY = 3
KEEP_COMMANDER_MAIN_PROXIMITY = 5

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
    combined_footprints: set[tuple[int, int]] = set()
    for b in buildings:
        combined_footprints |= b.base_shape.floor_tiles(b.base_rect)
    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    for b in buildings:
        own = b.base_shape.floor_tiles(b.base_rect)
        door_xy = _place_entry_door(
            b, rng, blocked=combined_footprints - own,
        )
        if door_xy is not None:
            neighbour = outside_neighbour(b, *door_xy)
            if neighbour is not None:
                door_map[neighbour] = (
                    b.id, door_xy[0], door_xy[1],
                )
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
    paint_surface_doors(site, SurfaceType.STREET)
    _place_keep_surface_npcs(site, rng)
    return site


def _place_keep_surface_npcs(
    site: Site, rng: random.Random,
) -> None:
    """Seed the keep surface with guards, one quartermaster,
    one commander.

    Order matters: the quartermaster claims a tile within
    :data:`KEEP_QUARTERMASTER_GATE_PROXIMITY` of the first gate;
    the commander picks a tile near the largest main building;
    guards scatter across the remaining walkable courtyard tiles.
    All three NPCs share the ``guardhouse`` faction (hostile until
    the narrative-systems milestone wires reputation-based stances).
    """
    surface = site.surface
    occupied: set[tuple[int, int]] = set()

    walkable: list[tuple[int, int]] = [
        (x, y)
        for y in range(surface.height)
        for x in range(surface.width)
        if _walkable_tile(surface, x, y)
    ]
    if not walkable:
        return
    walkable_set = set(walkable)

    gate_xy: tuple[int, int] | None = None
    if site.enclosure and site.enclosure.gates:
        gx, gy, _ = site.enclosure.gates[0]
        gate_xy = (gx, gy)

    if gate_xy is not None:
        qx, qy = _nearest_walkable(
            gate_xy, walkable_set, occupied,
            max_distance=KEEP_QUARTERMASTER_GATE_PROXIMITY,
        ) or _nearest_walkable(gate_xy, walkable_set, occupied)
        if qx is not None:
            surface.entities.append(EntityPlacement(
                entity_type="creature", entity_id="quartermaster",
                x=qx, y=qy,
            ))
            occupied.add((qx, qy))

    main = [b for b in site.buildings if "keep_main" in b.id]
    if main:
        largest = max(
            main,
            key=lambda b: b.base_rect.width * b.base_rect.height,
        )
        rect = largest.base_rect
        cx = rect.x + rect.width // 2
        cy = rect.y + rect.height // 2
        cxy, cyy = _nearest_walkable(
            (cx, cy), walkable_set, occupied,
            max_distance=KEEP_COMMANDER_MAIN_PROXIMITY,
        ) or _nearest_walkable((cx, cy), walkable_set, occupied)
        if cxy is not None:
            surface.entities.append(EntityPlacement(
                entity_type="creature", entity_id="commander",
                x=cxy, y=cyy,
            ))
            occupied.add((cxy, cyy))

    guard_count = rng.randint(*KEEP_GUARD_COUNT_RANGE)
    remaining = [p for p in walkable if p not in occupied]
    rng.shuffle(remaining)
    for (gx, gy) in remaining[:guard_count]:
        surface.entities.append(EntityPlacement(
            entity_type="creature", entity_id="guard",
            x=gx, y=gy,
        ))
        occupied.add((gx, gy))


def _walkable_tile(level: Level, x: int, y: int) -> bool:
    tile = level.tile_at(x, y)
    return (
        tile is not None
        and tile.terrain is Terrain.FLOOR
        and tile.feature is None
    )


def _nearest_walkable(
    target: tuple[int, int],
    walkable: set[tuple[int, int]],
    occupied: set[tuple[int, int]],
    max_distance: int | None = None,
) -> tuple[int, int] | None:
    """Return the walkable tile closest to ``target`` within
    Chebyshev ``max_distance`` (unbounded when None). ``None`` if
    no candidate exists."""
    best: tuple[int, int] | None = None
    best_d = None
    for (wx, wy) in walkable:
        if (wx, wy) in occupied:
            continue
        d = max(abs(wx - target[0]), abs(wy - target[1]))
        if max_distance is not None and d > max_distance:
            continue
        if best is None or d < best_d:
            best = (wx, wy)
            best_d = d
    return best


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
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_keep_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            required_walkable=req,
        ),
    )
    for f in floors:
        f.interior_floor = "stone"
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="stone",
        interior_floor="stone",
        interior_wall_material=(
            ARCHETYPE_CONFIG["keep"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _build_keep_floor(
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
        archetype="keep",
        tags=["keep_interior"],
        required_walkable=required_walkable,
    )


def _place_entry_door(
    building: Building, rng: random.Random,
    blocked: set[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    """Pick a perimeter tile to stamp as the entry door.

    ``blocked`` is the combined footprints of every other
    building; reject candidates whose outside-neighbour would
    fall inside another building's wall.
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
    surface.metadata.theme = "keep"
    surface.metadata.ambient = "keep"
    surface.metadata.prerevealed = True
    # Only building footprints block the courtyard surface -- no
    # 1-tile buffer ring. The SVG wall mask separates street from
    # building without help.
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)

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

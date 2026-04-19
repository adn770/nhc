"""Town site assembler.

See ``design/building_generator.md`` section 5.5. A town is a
set of small buildings in a grid, optionally surrounded by a
palisade, with STREET surface between buildings. Interiors mix
wood (residential / market) and stone (temple / garrison).

Four size classes tune building count, surface footprint, and
whether a palisade encloses the site:

- ``hamlet``: 3-4 buildings, no palisade, 30x22 surface.
- ``village``: 5-8 buildings, palisade, 50x30 surface.
- ``town``: 9-12 buildings, palisade, 62x36 surface.
- ``city``: 12-16 buildings, palisade, 74x42 surface.

Every size tags a subset of buildings with service roles
(``shop``, ``inn``, ``temple``, ``stable``, ``training``) and
places NPC ``EntityPlacement``s on the matching building's
ground floor: a merchant in the shop, an innkeeper + hirable
adventurer in the inn, a priest in the temple. Stable and
training are intentionally left unpopulated in v1 -- they exist
as labelled slots for future systems (mounts, XP sinks) to hook
into.

Supersedes the old single-level ``SettlementGenerator`` and
``generate_town`` helpers -- every settlement hex now routes
through this assembler regardless of size class.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    flip_building_stair_semantics, place_cross_floor_stairs,
)
from nhc.dungeon.model import (
    EntityPlacement, Level, LShape, Rect, RectShape, Room,
    RoomShape, SurfaceType, Terrain, Tile,
)
from nhc.dungeon.room_types import (
    SHOP_STOCK, TEMPLE_SERVICES_DEFAULT, TEMPLE_STOCK_DEFAULT,
)
from nhc.dungeon.site import (
    Enclosure, Site, outside_neighbour, paint_surface_doors,
)
from nhc.hexcrawl.model import Biome, DungeonRef


# ── Town tunable constants ───────────────────────────────────

TOWN_BUILDING_SIZE_RANGE = (5, 7)     # min 5 guarantees L-shape
                                      # has interior for stairs
TOWN_ROW_X_START = 6
TOWN_BUILDING_SPACING = 3                 # tile gap between buildings
TOWN_FLOOR_COUNT_RANGE = (1, 2)

TOWN_WOOD_BUILDING_PROBABILITY = 0.65    # rest are stone
TOWN_DESCENT_PROBABILITY = 0.08
TOWN_DESCENT_TEMPLATE = "procedural:crypt"

TOWN_PALISADE_PADDING = 3                # tiles beyond bbox
TOWN_GATE_COUNT_RANGE = (1, 2)
TOWN_GATE_LENGTH_TILES = 2

TOWN_SHAPE_POOL = ("rect", "lshape")


# Service role vocabulary. The first three roles own NPCs that
# ``_spawn_level_entities`` pulls into the ECS world on interior
# entry; stable and training stay empty (reserved slots).
SERVICE_ROLES_WITH_NPCS: tuple[str, ...] = ("shop", "inn", "temple")
SERVICE_ROLES_RESERVED: tuple[str, ...] = ("stable", "training")
SERVICE_ROLES: tuple[str, ...] = (
    SERVICE_ROLES_WITH_NPCS + SERVICE_ROLES_RESERVED
)


@dataclass(frozen=True)
class _TownSizeConfig:
    """Per-size layout tunables."""

    building_count_range: tuple[int, int]
    surface_width: int
    surface_height: int
    row_y: tuple[int, int]
    has_palisade: bool


@dataclass(frozen=True)
class _BiomeOverrides:
    """Biome-driven tweaks applied on top of the size-class config.

    ``wall_material`` / ``interior_floor`` force every building to
    the given material when set; ``None`` falls through to the
    default wood/brick/stone roll. ``suppress_palisade`` flips the
    size-class palisade off regardless of has_palisade. ``skew_small``
    clamps the building-count roll to the lower half of the range.
    ``ambient`` overrides ``surface.metadata.ambient`` when set.
    """

    wall_material: str | None = None
    interior_floor: str | None = None
    suppress_palisade: bool = False
    skew_small: bool = False
    ambient: str | None = None


_BIOME_OVERRIDES: dict[Biome, _BiomeOverrides] = {
    Biome.MOUNTAIN: _BiomeOverrides(
        wall_material="stone", interior_floor="stone",
        suppress_palisade=True, skew_small=True,
    ),
    Biome.DRYLANDS: _BiomeOverrides(
        wall_material="adobe", interior_floor="earth",
    ),
    Biome.MARSH: _BiomeOverrides(
        wall_material="wood", interior_floor="wood",
        ambient="stilted",
    ),
}


def _biome_overrides(biome: Biome | None) -> _BiomeOverrides:
    """Return the override bundle for ``biome`` (or empty defaults)."""
    if biome is None:
        return _BiomeOverrides()
    return _BIOME_OVERRIDES.get(biome, _BiomeOverrides())


_SIZE_CLASSES: dict[str, _TownSizeConfig] = {
    "hamlet": _TownSizeConfig(
        building_count_range=(3, 4),
        surface_width=30,
        surface_height=22,
        row_y=(4, 13),
        has_palisade=False,
    ),
    "village": _TownSizeConfig(
        building_count_range=(5, 8),
        surface_width=50,
        surface_height=30,
        row_y=(6, 17),
        has_palisade=True,
    ),
    "town": _TownSizeConfig(
        building_count_range=(9, 12),
        surface_width=62,
        surface_height=36,
        row_y=(8, 21),
        has_palisade=True,
    ),
    "city": _TownSizeConfig(
        building_count_range=(12, 16),
        surface_width=74,
        surface_height=42,
        row_y=(10, 25),
        has_palisade=True,
    ),
}


def assemble_town(
    site_id: str,
    rng: random.Random,
    size_class: str = "village",
    biome: Biome | None = None,
) -> Site:
    """Assemble a town site.

    ``size_class`` must be one of ``hamlet``, ``village``,
    ``town`` or ``city``. Defaults to ``village`` so legacy
    call sites and tests remain unchanged.

    ``biome`` is an optional :class:`Biome` that lets the
    assembler tweak its defaults via :data:`_BIOME_OVERRIDES`
    without growing a new feature type. Mountain settlements get
    stone walls, no palisade, and skewed-small building counts;
    drylands towns land adobe walls over packed-earth floors;
    marsh towns switch to stilted wood with a ``"stilted"``
    surface ambient marker the frontend can raise a tile for.
    All other biomes fall through to the unmodified defaults.
    """
    if size_class not in _SIZE_CLASSES:
        raise ValueError(f"unknown town size_class: {size_class!r}")
    config = _SIZE_CLASSES[size_class]
    overrides = _biome_overrides(biome)

    if overrides.skew_small:
        lo, hi = config.building_count_range
        # Clamp to the lower half so small-biome sites never push
        # to the top of the band. Guarantees at least one building.
        skewed_hi = max(lo, (lo + hi) // 2)
        n_buildings = rng.randint(lo, skewed_hi)
    else:
        n_buildings = rng.randint(*config.building_count_range)

    buildings = _place_buildings(
        site_id, rng, n_buildings, config, overrides=overrides,
    )
    role_assignments = _assign_service_roles(rng, buildings)

    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    for b in buildings:
        door_xy = _place_entry_door(b, rng)
        if door_xy is not None:
            neighbour = outside_neighbour(b, *door_xy)
            if neighbour is not None:
                door_map[neighbour] = (
                    b.id, door_xy[0], door_xy[1],
                )
        b.validate()

    # Mountain lodges read best without a palisade; everything else
    # inherits the size-class default.
    if config.has_palisade and not overrides.suppress_palisade:
        enclosure = _build_palisade(buildings, config, rng)
    else:
        enclosure = None
    surface = _build_town_surface(
        f"{site_id}_surface", buildings, enclosure, config,
    )
    if overrides.ambient is not None:
        surface.metadata.ambient = overrides.ambient

    site = Site(
        id=site_id,
        kind="town",
        buildings=buildings,
        surface=surface,
        enclosure=enclosure,
    )
    site.building_doors.update(door_map)
    paint_surface_doors(site, SurfaceType.STREET)
    _place_service_npcs(buildings, role_assignments, rng)
    return site


def _place_buildings(
    site_id: str, rng: random.Random,
    n_buildings: int, config: _TownSizeConfig,
    overrides: _BiomeOverrides | None = None,
) -> list[Building]:
    """Distribute ``n_buildings`` across two rows of the site."""
    overrides = overrides or _BiomeOverrides()
    per_row = (n_buildings + 1) // 2
    buildings: list[Building] = []
    for row_idx, base_y in enumerate(config.row_y):
        x_cursor = TOWN_ROW_X_START
        for i in range(per_row):
            if len(buildings) >= n_buildings:
                break
            w = rng.randint(*TOWN_BUILDING_SIZE_RANGE)
            h = rng.randint(*TOWN_BUILDING_SIZE_RANGE)
            rect = Rect(x_cursor, base_y, w, h)
            shape = _pick_shape(rng)
            n_floors = rng.randint(*TOWN_FLOOR_COUNT_RANGE)
            if overrides.interior_floor is not None:
                interior = overrides.interior_floor
            else:
                is_wood = (
                    rng.random() < TOWN_WOOD_BUILDING_PROBABILITY
                )
                interior = "wood" if is_wood else "stone"
            descent: DungeonRef | None = None
            if rng.random() < TOWN_DESCENT_PROBABILITY:
                descent = DungeonRef(
                    template=TOWN_DESCENT_TEMPLATE,
                )
            building = _build_town_building(
                f"{site_id}_b{row_idx}_{i}", shape, rect,
                n_floors, descent, interior, rng,
                wall_override=overrides.wall_material,
            )
            buildings.append(building)
            x_cursor += w + TOWN_BUILDING_SPACING
    return buildings


def _assign_service_roles(
    rng: random.Random, buildings: list[Building],
) -> dict[str, str]:
    """Pick which buildings fill which service slots.

    Returns ``{building_id: role}`` for every tagged building.
    The three NPC-bearing roles (``shop``, ``inn``, ``temple``)
    are filled first, then the reserved ``stable`` / ``training``
    slots if there are enough buildings; remaining buildings stay
    untagged (plain residential). Hamlets with only 3 buildings
    will cover exactly the three NPC roles; larger sites fill more
    slots and leave the rest as residential.
    """
    if not buildings:
        return {}
    shuffled = list(buildings)
    rng.shuffle(shuffled)

    role_order = list(SERVICE_ROLES_WITH_NPCS) + list(
        SERVICE_ROLES_RESERVED,
    )
    assignments: dict[str, str] = {}
    for role, building in zip(role_order, shuffled):
        assignments[building.id] = role
        building.floors[0].rooms[0].tags.append(role)
    return assignments


def _pick_shape(rng: random.Random) -> RoomShape:
    key = rng.choice(TOWN_SHAPE_POOL)
    if key == "rect":
        return RectShape()
    return LShape(corner=rng.choice(LShape._VALID_CORNERS))


def _build_town_building(
    building_id: str, base_shape: RoomShape, base_rect: Rect,
    n_floors: int, descent: DungeonRef | None,
    interior: str, rng: random.Random,
    wall_override: str | None = None,
) -> Building:
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_town_floor(
            building_id, idx, base_shape, base_rect,
        )
        level.interior_floor = interior
        floors.append(level)
    if wall_override is not None:
        wall_material = wall_override
    else:
        wall_material = "brick" if interior == "wood" else "stone"
    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material=wall_material,
        interior_floor=interior,
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    flip_building_stair_semantics(building)
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


def _build_palisade(
    buildings: list[Building], config: _TownSizeConfig,
    rng: random.Random,
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
    gate_y = (
        config.row_y[0] + TOWN_BUILDING_SIZE_RANGE[1]
        + (
            config.row_y[1] - config.row_y[0]
            - TOWN_BUILDING_SIZE_RANGE[1]
        ) // 2
    )
    gate_count = rng.randint(*TOWN_GATE_COUNT_RANGE)
    sides = ["west", "east"]
    rng.shuffle(sides)
    gates: list[tuple[int, int, int]] = []
    for i in range(gate_count):
        gx = min_x if sides[i] == "west" else max_x
        gates.append((gx, gate_y, TOWN_GATE_LENGTH_TILES))
    return Enclosure(
        kind="palisade", polygon=polygon, gates=gates,
    )


def _build_town_surface(
    surface_id: str, buildings: list[Building],
    enclosure: Enclosure | None, config: _TownSizeConfig,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        config.surface_width, config.surface_height,
    )
    surface.metadata.theme = "town"
    surface.metadata.ambient = "town"
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)
        for (x, y) in b.base_shape.floor_tiles(b.base_rect):
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    blocked.add((x + dx, y + dy))

    if enclosure is not None:
        xs = [p[0] for p in enclosure.polygon]
        ys = [p[1] for p in enclosure.polygon]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        # Enclosure polygon sits at tile boundaries: vertex (x, y)
        # aligns with the top-left corner of tile (x, y). A tile
        # at (tx, ty) is inside the polygon only when tx+1 <= max_x
        # and ty+1 <= max_y, so the STREET fill stops one row short
        # of max_x / max_y -- otherwise tiles at max_x or max_y
        # would sit outside the palisade and read as "one tile
        # off".
        y_start = max(0, min_y)
        y_end = min(surface.height, max_y)
        x_start = max(0, min_x)
        x_end = min(surface.width, max_x)
    else:
        # Hamlets have no palisade; the walkable area is the
        # whole surface minus building footprints.
        y_start, y_end = 0, surface.height
        x_start, x_end = 0, surface.width

    for y in range(y_start, y_end):
        for x in range(x_start, x_end):
            if (x, y) in blocked:
                continue
            surface.tiles[y][x] = Tile(
                terrain=Terrain.FLOOR,
                surface_type=SurfaceType.STREET,
            )
    return surface


def _place_service_npcs(
    buildings: list[Building],
    role_assignments: dict[str, str],
    rng: random.Random,
) -> None:
    """Append NPC ``EntityPlacement``s to the ground floor of each
    building tagged with a service role that owns an NPC.

    The NPC stands on the room centre; extra payload (shop stock,
    temple services, adventurer level) is copied verbatim into the
    placement so ``_spawn_level_entities`` wires it up when the
    player enters the building.
    """
    by_id = {b.id: b for b in buildings}
    for bid, role in role_assignments.items():
        building = by_id[bid]
        ground = building.ground
        if not ground.rooms:
            continue
        room = ground.rooms[0]
        cx, cy = room.rect.center
        if role == "shop":
            ground.entities.append(_merchant_placement(cx, cy, rng))
        elif role == "temple":
            ground.entities.append(_priest_placement(cx, cy))
        elif role == "inn":
            ground.entities.append(_adventurer_placement(cx, cy))
            ground.entities.append(_innkeeper_placement(cx, cy))


def _merchant_placement(
    cx: int, cy: int, rng: random.Random,
) -> EntityPlacement:
    """Merchant at the shop-room centre, stocked from depth-1 pool."""
    pool = SHOP_STOCK[1]
    ids, weights = zip(*pool)
    count = rng.randint(4, 7)
    stock = rng.choices(list(ids), weights=list(weights), k=count)
    seen: set[str] = set()
    unique: list[str] = []
    for iid in stock:
        if iid not in seen:
            seen.add(iid)
            unique.append(iid)
    return EntityPlacement(
        entity_type="creature", entity_id="merchant",
        x=cx, y=cy, extra={"shop_stock": unique},
    )


def _priest_placement(cx: int, cy: int) -> EntityPlacement:
    return EntityPlacement(
        entity_type="creature", entity_id="priest",
        x=cx, y=cy,
        extra={
            "temple_services": list(TEMPLE_SERVICES_DEFAULT),
            "shop_stock": list(TEMPLE_STOCK_DEFAULT),
        },
    )


def _adventurer_placement(cx: int, cy: int) -> EntityPlacement:
    """Hirable level-1 adventurer at the inn-room centre."""
    return EntityPlacement(
        entity_type="creature", entity_id="adventurer",
        x=cx, y=cy, extra={"adventurer_level": 1},
    )


def _innkeeper_placement(cx: int, cy: int) -> EntityPlacement:
    """Innkeeper one tile east of the inn-room centre so the pair
    does not overlap with the adventurer."""
    return EntityPlacement(
        entity_type="creature", entity_id="innkeeper",
        x=cx + 1, y=cy,
    )

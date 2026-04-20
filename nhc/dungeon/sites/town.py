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
    build_floors_with_stairs,
)
from nhc.dungeon.interior._floor import build_building_floor
from nhc.dungeon.interior.registry import ARCHETYPE_CONFIG
from nhc.dungeon.model import (
    EntityPlacement, Level, LShape, Rect, RectShape,
    RoomShape, SurfaceType, Terrain, Tile,
)
from nhc.dungeon.room_types import (
    SHOP_STOCK, TEMPLE_SERVICES_DEFAULT, TEMPLE_STOCK_DEFAULT,
)
from nhc.dungeon.site import (
    Enclosure, Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.dungeon.sites._placement import safe_floor_near
from nhc.hexcrawl.model import Biome, DungeonRef


# ── Town tunable constants ───────────────────────────────────

# Default building size range for untagged (residential) slots.
# Per-archetype overrides land in M14 when ARCHETYPE_CONFIG drives
# per-role sizing end-to-end; for now every town building still
# draws from this single range, read from the registry so
# retuning residentials is one edit away.
_RESIDENTIAL_SIZE_RANGE = ARCHETYPE_CONFIG["residential"].size_range
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
        surface_width=36,
        surface_height=26,
        row_y=(4, 15),
        has_palisade=False,
    ),
    "village": _TownSizeConfig(
        building_count_range=(5, 7),
        surface_width=58,
        surface_height=34,
        row_y=(5, 19),
        has_palisade=True,
    ),
    "town": _TownSizeConfig(
        building_count_range=(8, 10),
        surface_width=72,
        surface_height=42,
        row_y=(6, 23),
        has_palisade=True,
    ),
    "city": _TownSizeConfig(
        building_count_range=(10, 13),
        surface_width=84,
        surface_height=50,
        row_y=(6, 28),
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

    combined_footprints: set[tuple[int, int]] = set()
    for b in buildings:
        combined_footprints |= b.base_shape.floor_tiles(b.base_rect)
    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    for b in buildings:
        own = b.base_shape.floor_tiles(b.base_rect)
        others = combined_footprints - own
        door_xy = _place_entry_door(b, rng, blocked=others)
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
    _lock_shop_doors(buildings, role_assignments, rng)
    return site


def _place_buildings(
    site_id: str, rng: random.Random,
    n_buildings: int, config: _TownSizeConfig,
    overrides: _BiomeOverrides | None = None,
) -> list[Building]:
    """Greedy row-pack ``n_buildings`` across the town surface.

    Per-building ``(w, h)`` sizes are drawn up front, then laid out
    left-to-right starting at ``config.row_y[0]``. When the next
    building would exceed ``surface_width - TOWN_ROW_X_START`` on the
    current row, the cursor wraps to a new row whose top ``y`` is
    ``previous_row_top + tallest_in_previous_row + spacing``. This
    replaces the old two-fixed-rows layout that assumed a uniform
    residential size range and overflowed ``city`` seeds when the
    per-row count pushed the cursor past the surface width.
    """
    overrides = overrides or _BiomeOverrides()
    sizes = [
        (
            rng.randint(*_RESIDENTIAL_SIZE_RANGE),
            rng.randint(*_RESIDENTIAL_SIZE_RANGE),
        )
        for _ in range(n_buildings)
    ]
    placements = _greedy_pack(sizes, config)
    buildings: list[Building] = []
    for i, (x, y, w, h) in enumerate(placements):
        rect = Rect(x, y, w, h)
        shape = _pick_shape(rng)
        n_floors = rng.randint(*TOWN_FLOOR_COUNT_RANGE)
        if overrides.interior_floor is not None:
            interior = overrides.interior_floor
        else:
            is_wood = rng.random() < TOWN_WOOD_BUILDING_PROBABILITY
            interior = "wood" if is_wood else "stone"
        descent: DungeonRef | None = None
        if rng.random() < TOWN_DESCENT_PROBABILITY:
            descent = DungeonRef(template=TOWN_DESCENT_TEMPLATE)
        building = _build_town_building(
            f"{site_id}_b{i}", shape, rect,
            n_floors, descent, interior, rng,
            wall_override=overrides.wall_material,
        )
        buildings.append(building)
    return buildings


def _greedy_pack(
    sizes: list[tuple[int, int]], config: _TownSizeConfig,
) -> list[tuple[int, int, int, int]]:
    """Return ``[(x, y, w, h)]`` placements for the given sizes.

    Wraps to a new row when the cursor would push past
    ``surface_width - TOWN_ROW_X_START``. Row heights grow from the
    tallest building placed so far in that row.
    """
    row_x_limit = config.surface_width - TOWN_ROW_X_START
    placements: list[tuple[int, int, int, int]] = []
    row_top = config.row_y[0]
    x_cursor = TOWN_ROW_X_START
    row_height = 0
    for w, h in sizes:
        # Wrap to the next row only when there is already something
        # on this row — a single oversized building may exceed the
        # row limit but still has to go somewhere.
        if x_cursor > TOWN_ROW_X_START and x_cursor + w > row_x_limit:
            row_top += row_height + TOWN_BUILDING_SPACING
            x_cursor = TOWN_ROW_X_START
            row_height = 0
        placements.append((x_cursor, row_top, w, h))
        x_cursor += w + TOWN_BUILDING_SPACING
        row_height = max(row_height, h)
    return placements


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
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_town_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            required_walkable=req,
        ),
    )
    for f in floors:
        f.interior_floor = interior
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
        interior_wall_material=(
            ARCHETYPE_CONFIG["residential"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _build_town_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    # Town buildings default to the residential archetype; M16 will
    # re-roll the per-role archetype (shop / inn / temple / etc.)
    # before partitioning once safe_floor_near() is in place.
    return build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype="residential",
        tags=["town_interior"],
        required_walkable=required_walkable,
    )


def _place_entry_door(
    building: Building, rng: random.Random,
    blocked: set[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    """Pick a perimeter tile to stamp as the entry door.

    ``blocked`` carries the combined footprints of every OTHER
    building in the site. A candidate is rejected when its
    outside-neighbour (the surface tile the door opens onto) is in
    ``blocked`` -- that would place the surface door inside another
    building's footprint, where no walkable street tile exists.
    This is what used to strand doors at L-shape inner corners.
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


def _main_street_y(buildings: list[Building]) -> int:
    """Return a y coordinate sitting in the widest gap between
    building rows, used as the main-street / gate y.

    Falls back to the midpoint of the building bounding box when
    every y is occupied by at least one building.
    """
    if not buildings:
        return 0
    occupied: set[int] = set()
    for b in buildings:
        for y in range(b.base_rect.y, b.base_rect.y2):
            occupied.add(y)
    min_y = min(b.base_rect.y for b in buildings)
    max_y = max(b.base_rect.y2 for b in buildings) - 1
    best_len = 0
    best_mid = (min_y + max_y) // 2
    cur_start: int | None = None
    for y in range(min_y, max_y + 2):
        if y not in occupied and y <= max_y:
            if cur_start is None:
                cur_start = y
        else:
            if cur_start is not None:
                run_len = y - cur_start
                if run_len > best_len:
                    best_len = run_len
                    best_mid = (cur_start + y - 1) // 2
                cur_start = None
    return best_mid


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
    # town -- not at random midpoints of a random edge. With
    # greedy row packing, the gate sits in the biggest vertical
    # gap between building rows so variable building heights don't
    # push the street inside a building.
    gate_y = _main_street_y(buildings)
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
    surface.metadata.prerevealed = True
    # Only the building footprints themselves are blocked from the
    # walkable surface -- no 1-tile buffer ring. The ring used to
    # seal the concave notch of L-shaped buildings, stranding any
    # door placed in it; the SVG wall mask handles the visual
    # separation between street and building without a ring.
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)

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
        cx, cy = safe_floor_near(
            ground, *room.rect.center, room,
        )
        if role == "shop":
            ground.entities.append(_merchant_placement(cx, cy, rng))
        elif role == "temple":
            ground.entities.append(_priest_placement(cx, cy))
        elif role == "inn":
            ground.entities.append(_adventurer_placement(cx, cy))
            ix, iy = safe_floor_near(
                ground, cx + 1, cy, room,
            )
            ground.entities.append(_innkeeper_placement(ix, iy))


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


def _lock_shop_doors(
    buildings: list[Building],
    role_assignments: dict[str, str],
    rng: random.Random,
) -> None:
    """Convert one interior ``door_closed`` to ``door_locked`` on
    each shop building, gated by ``ARCHETYPE_CONFIG["shop"]
    .locked_door_rate``.

    See ``design/building_interiors.md`` door rules: one locked
    door max per shop, door separating the smallest BSP leaf. The
    smallest-leaf rule lands cleanly once shops route through
    RectBSPPartitioner; for the current residential (Divided)
    layout the single interior door is already the split between
    two rooms — locking it satisfies the spirit of the rule.
    """
    rate = ARCHETYPE_CONFIG["shop"].locked_door_rate
    if rate <= 0:
        return
    by_id = {b.id: b for b in buildings}
    for bid, role in role_assignments.items():
        if role != "shop":
            continue
        if rng.random() >= rate:
            continue
        ground = by_id[bid].ground
        door_tile = _smallest_room_door(ground, by_id[bid])
        if door_tile is None:
            continue
        x, y = door_tile
        ground.tiles[y][x].feature = "door_locked"


def _smallest_room_door(
    ground: Level, building: Building,
) -> tuple[int, int] | None:
    """Return the interior-door tile adjacent to the smallest room.

    Interior doors live off the shared perimeter; the smallest
    room is picked by :meth:`Room.floor_tiles` count. Entry doors
    (on the perimeter) are skipped so locking never blocks the
    building entrance.
    """
    perim = building.shared_perimeter()
    door_candidates: list[tuple[int, int]] = []
    for y, row in enumerate(ground.tiles):
        for x, tile in enumerate(row):
            if tile.feature != "door_closed":
                continue
            if (x, y) in perim:
                continue
            door_candidates.append((x, y))
    if not door_candidates:
        return None
    smallest_room = min(
        ground.rooms, key=lambda r: len(r.floor_tiles()),
    )
    adjacent = [
        (dx, dy) for (dx, dy) in door_candidates
        if any(
            (dx + ox, dy + oy) in smallest_room.floor_tiles()
            for (ox, oy) in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        )
    ]
    if adjacent:
        return adjacent[0]
    return door_candidates[0]


def _innkeeper_placement(cx: int, cy: int) -> EntityPlacement:
    """Innkeeper near the inn-room centre; caller nudges the coord
    off the adventurer via :func:`safe_floor_near`."""
    return EntityPlacement(
        entity_type="creature", entity_id="innkeeper",
        x=cx, y=cy,
    )

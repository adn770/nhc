"""Farm site assembler.

See ``design/building_generator.md`` section 5.2. A farm is 1-2
small wood-interior buildings (farmhouse + optional barn)
surrounded by a large FIELD region, with a few GARDEN tiles in a
ring around the farmhouse. No enclosure. Rare descent (~10%,
farmhouse only) at MEDIUM tier; SMALL tier (sub-hex minor
feature) drops the barn and the descent.
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
    Level, LShape, Rect, RectShape, RoomShape, SurfaceType,
    Terrain, Tile,
)
from nhc.hexcrawl.model import DungeonRef
from nhc.sites._types import SiteTier
from nhc.sites._site import (
    Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)


# ── Farm tunable constants (tier-indexed) ────────────────────

FARM_SURFACE_WIDTH: dict[SiteTier, int] = {
    SiteTier.TINY: 15,
    SiteTier.SMALL: 30,
}
FARM_SURFACE_HEIGHT: dict[SiteTier, int] = {
    SiteTier.TINY: 10,
    SiteTier.SMALL: 22,
}
FARM_FARMHOUSE_POS: dict[SiteTier, tuple[int, int]] = {
    SiteTier.TINY: (4, 2),
    SiteTier.SMALL: (5, 4),
}
FARM_FARMHOUSE_SIZE: dict[SiteTier, tuple[int, int]] = {
    SiteTier.TINY: (7, 6),
    SiteTier.SMALL: (8, 7),
}
FARM_BARN_POS: dict[SiteTier, tuple[int, int] | None] = {
    SiteTier.TINY: None,
    SiteTier.SMALL: (18, 10),
}
FARM_BARN_SIZE: dict[SiteTier, tuple[int, int] | None] = {
    SiteTier.TINY: None,
    SiteTier.SMALL: (6, 6),
}
FARM_BARN_PROBABILITY: dict[SiteTier, float] = {
    SiteTier.TINY: 0.0,
    SiteTier.SMALL: 0.5,
}
FARM_DESCENT_PROBABILITY: dict[SiteTier, float] = {
    SiteTier.TINY: 0.0,
    SiteTier.SMALL: 0.1,
}
FARM_FLOOR_COUNT_RANGE = (1, 2)
FARM_DESCENT_TEMPLATE = "procedural:crypt"
FARM_GARDEN_RING = 1  # tiles of garden around farmhouse perimeter
FARM_SHAPE_POOL = ("rect", "lshape")


def assemble_farm(
    site_id: str, rng: random.Random,
    *, tier: SiteTier = SiteTier.SMALL,
) -> Site:
    """Assemble a farm site.

    Returns a :class:`Site` with one farmhouse building and an
    optional barn, a FIELD-dominated surface level, and a
    GARDEN ring around the farmhouse. No enclosure. ``tier``
    selects the footprint — ``TINY`` drops the barn and the
    descent; ``SMALL`` keeps the macro-feature defaults
    (optional barn + occasional descent).
    """
    farmhouse_pos = FARM_FARMHOUSE_POS[tier]
    farmhouse_size = FARM_FARMHOUSE_SIZE[tier]
    farmhouse_rect = Rect(
        farmhouse_pos[0], farmhouse_pos[1],
        farmhouse_size[0], farmhouse_size[1],
    )
    farmhouse_shape = _pick_shape(rng)
    farmhouse_floors = rng.randint(*FARM_FLOOR_COUNT_RANGE)
    farmhouse_descent: DungeonRef | None = None
    if rng.random() < FARM_DESCENT_PROBABILITY[tier]:
        farmhouse_descent = DungeonRef(template=FARM_DESCENT_TEMPLATE)
    farmhouse = _build_farm_building(
        f"{site_id}_farmhouse", farmhouse_shape, farmhouse_rect,
        farmhouse_floors, descent=farmhouse_descent, rng=rng,
    )

    buildings = [farmhouse]
    barn_pos = FARM_BARN_POS[tier]
    barn_size = FARM_BARN_SIZE[tier]
    if (
        barn_pos is not None
        and barn_size is not None
        and rng.random() < FARM_BARN_PROBABILITY[tier]
    ):
        barn_rect = Rect(
            barn_pos[0], barn_pos[1],
            barn_size[0], barn_size[1],
        )
        barn_shape = RectShape()  # barns are always rect
        barn_floors = rng.randint(1, 2)
        barn = _build_farm_building(
            f"{site_id}_barn", barn_shape, barn_rect,
            barn_floors, descent=None, rng=rng,
        )
        buildings.append(barn)

    surface = _build_farm_surface(
        f"{site_id}_surface", buildings, farmhouse, tier,
    )

    site = Site(
        id=site_id,
        kind="farm",
        buildings=buildings,
        surface=surface,
        enclosure=None,
    )
    for b in buildings:
        for door_xy in _find_entry_doors(b):
            neighbour = outside_neighbour(b, *door_xy)
            if neighbour is not None:
                site.building_doors[neighbour] = (
                    b.id, door_xy[0], door_xy[1],
                )
    paint_surface_doors(site, SurfaceType.FIELD)
    return site


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
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        descent=descent,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_farm_floor(
            building_id, idx, base_shape, base_rect, n, rng,
            required_walkable=req,
        ),
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
        interior_wall_material=(
            ARCHETYPE_CONFIG["farm_main"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    _place_entry_door(building, rng)
    building.validate()
    return building


def _build_farm_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    level = build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=base_shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype="farm_main",
        tags=["farm_interior"],
        required_walkable=required_walkable,
    )
    level.interior_floor = "wood"
    return level


def _place_entry_door(
    building: Building, rng: random.Random,
    blocked: set[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    """Pick a perimeter tile to stamp as the entry door.

    ``blocked`` carries any other buildings' footprints so the
    door's outside-neighbour cannot land inside a neighbouring
    wall. Farm currently runs the picker before the optional
    barn exists, so ``blocked`` is empty in that path -- the
    parameter is present for symmetry with the multi-building
    assemblers.
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


def _find_entry_doors(
    building: Building,
) -> list[tuple[int, int]]:
    """Return every ``door_closed`` tile on the building's perimeter."""
    ground = building.ground
    out: list[tuple[int, int]] = []
    for (px, py) in building.shared_perimeter():
        if ground.tiles[py][px].feature == "door_closed":
            out.append((px, py))
    return out


def _build_farm_surface(
    surface_id: str, buildings: list[Building],
    farmhouse: Building, tier: SiteTier,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        FARM_SURFACE_WIDTH[tier], FARM_SURFACE_HEIGHT[tier],
    )
    # Collect all footprint tiles across buildings. The old code
    # also blocked a 1-tile buffer ring; dropped so fields reach
    # right up to the wall (the SVG wall mask handles the visual
    # break without it).
    blocked: set[tuple[int, int]] = set()
    for b in buildings:
        blocked |= b.base_shape.floor_tiles(b.base_rect)

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

    # The farm surface is an outdoor place — match the keep / town
    # / cottage / orchard convention so the renderer skips the
    # dungeon hatching and the client ships it prerevealed (entity
    # visibility still gates on FOV).
    surface.metadata.theme = "farm"
    surface.metadata.prerevealed = True
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

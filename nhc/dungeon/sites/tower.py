"""Tower site assembler.

See ``design/building_generator.md`` section 5.1. A tower is one
Building with 2-6 floors sharing a circular, octagonal, or square
base shape. No enclosure. One entry door on the ground-floor
perimeter. Optional subterranean descent (~30% of towers). The
topmost floor is wood when the tower has 3+ floors; otherwise
stone throughout.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    place_cross_floor_stairs,
)
from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, Rect, RectShape, Room,
    RoomShape, Terrain, Tile,
)
from nhc.dungeon.site import Site, outside_neighbour, stamp_building_door
from nhc.dungeon.sites._shell import compose_shell
from nhc.hexcrawl.model import Biome, DungeonRef


# ── Tower tunable constants ───────────────────────────────────

TOWER_SIZE_RANGE = (7, 11)                  # base rect width = height
TOWER_FLOOR_COUNT_RANGE = (2, 6)
TOWER_DESCENT_PROBABILITY = 0.3
TOWER_DESCENT_TEMPLATE = "procedural:crypt"
TOWER_SHAPE_POOL = ("circle", "octagon", "square")


def assemble_tower(
    site_id: str, rng: random.Random,
    biome: Biome | None = None,
) -> Site:
    """Assemble a tower site from ``rng``.

    Returns a :class:`Site` with exactly one :class:`Building`, no
    enclosure, and a small square ``surface`` level framing the
    tower footprint. Interior rendering is handled by
    ``render_floor_svg`` per floor and the building-wall SVG
    renderers in later integration milestones.

    ``biome`` is an optional :class:`Biome` that lets the
    assembler apply per-biome overrides matching v1's tile-only
    split (design/biome_features.md §8). Forest watchtowers cap
    at 2 floors and stamp ``roof_material="wood"`` on the
    Building; mountain towers force every floor's wall + interior
    to stone. All other biomes fall through to the unmodified
    defaults.
    """
    shape_key = rng.choice(TOWER_SHAPE_POOL)
    size = rng.randint(*TOWER_SIZE_RANGE)
    base_rect = Rect(1, 1, size, size)

    base_shape: RoomShape
    if shape_key == "circle":
        base_shape = CircleShape()
    elif shape_key == "octagon":
        base_shape = OctagonShape()
    else:
        base_shape = RectShape()

    n_floors = rng.randint(*TOWER_FLOOR_COUNT_RANGE)
    if biome is Biome.FOREST:
        # Forest watchtowers read as short wooden spotter
        # platforms, not full stone towers.
        n_floors = min(2, n_floors)

    descent: DungeonRef | None = None
    if rng.random() < TOWER_DESCENT_PROBABILITY:
        descent = DungeonRef(template=TOWER_DESCENT_TEMPLATE)

    mountain = biome is Biome.MOUNTAIN
    interior_floor_default = "stone"
    wall_material = "stone" if mountain else "brick"
    roof_material: str | None = None
    if biome is Biome.FOREST:
        roof_material = "wood"

    building_id = f"{site_id}_tower"
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_tower_floor(
            building_id, idx, base_shape, base_rect,
        )
        floors.append(level)

    if not mountain and n_floors >= 3:
        floors[-1].interior_floor = "wood"

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material=wall_material,
        interior_floor=interior_floor_default,
        roof_material=roof_material,
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    door_xy = _place_entry_door(building, rng)
    building.validate()

    surface = Level.create_empty(
        f"{site_id}_surface", f"{site_id} surface", 0,
        base_rect.x + base_rect.width + 2,
        base_rect.y + base_rect.height + 2,
    )

    site = Site(
        id=site_id,
        kind="tower",
        buildings=[building],
        surface=surface,
        enclosure=None,
    )
    if door_xy is not None:
        neighbour = outside_neighbour(building, *door_xy)
        if neighbour is not None:
            site.building_doors[neighbour] = (
                building.id, door_xy[0], door_xy[1],
            )
    return site


def _build_tower_floor(
    building_id: str, floor_idx: int,
    base_shape: RoomShape, base_rect: Rect,
) -> Level:
    """Create a single-room Level with the footprint carved as FLOOR.

    Walls fill the 8-neighbours of every floor tile that are not
    themselves floor, giving the standard Dyson-style wall ring.
    """
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
    compose_shell(level, {building_id: footprint})

    room = Room(
        id=f"{building_id}_f{floor_idx}_room",
        rect=Rect(
            base_rect.x, base_rect.y,
            base_rect.width, base_rect.height,
        ),
        shape=base_shape,
        tags=["tower_interior"] + (
            ["entrance"] if floor_idx == 0 else []
        ),
    )
    level.rooms = [room]
    level.building_id = building_id
    level.floor_index = floor_idx
    return level


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    """Mark one ground-floor perimeter tile as ``door_closed``.

    Returns the ``(x, y)`` of the placed door, or ``None`` when no
    eligible perimeter tile exists (small shape edge-case).
    """
    ground = building.ground
    perim = building.shared_perimeter()
    candidates: list[tuple[int, int]] = []
    for (px, py) in perim:
        tile = ground.tiles[py][px]
        if tile.feature is not None:
            continue
        # Prefer perimeter tiles with a WALL neighbour outside the
        # building -- those face the surface.
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
    stamp_building_door(building, dx, dy)
    return (dx, dy)

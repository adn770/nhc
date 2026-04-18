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
from nhc.dungeon.generators._stairs import place_cross_floor_stairs
from nhc.dungeon.model import (
    CircleShape, Level, OctagonShape, Rect, RectShape, Room,
    RoomShape, Terrain, Tile,
)
from nhc.dungeon.site import Site
from nhc.hexcrawl.model import DungeonRef


# ── Tower tunable constants ───────────────────────────────────

TOWER_SIZE_RANGE = (7, 11)                  # base rect width = height
TOWER_FLOOR_COUNT_RANGE = (2, 6)
TOWER_DESCENT_PROBABILITY = 0.3
TOWER_DESCENT_TEMPLATE = "procedural:crypt"
TOWER_SHAPE_POOL = ("circle", "octagon", "square")


def assemble_tower(
    site_id: str, rng: random.Random,
) -> Site:
    """Assemble a tower site from ``rng``.

    Returns a :class:`Site` with exactly one :class:`Building`, no
    enclosure, and a small square ``surface`` level framing the
    tower footprint. Interior rendering is handled by
    ``render_floor_svg`` per floor and the building-wall SVG
    renderers in later integration milestones.
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

    descent: DungeonRef | None = None
    if rng.random() < TOWER_DESCENT_PROBABILITY:
        descent = DungeonRef(template=TOWER_DESCENT_TEMPLATE)

    building_id = f"{site_id}_tower"
    floors: list[Level] = []
    for idx in range(n_floors):
        level = _build_tower_floor(
            building_id, idx, base_shape, base_rect,
        )
        floors.append(level)

    if n_floors >= 3:
        floors[-1].interior_floor = "wood"

    building = Building(
        id=building_id,
        base_shape=base_shape,
        base_rect=base_rect,
        floors=floors,
        descent=descent,
        wall_material="brick",
        interior_floor="stone",
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    _flip_stair_semantics_for_tower(building)
    _place_entry_door(building, rng)
    building.validate()

    surface = Level.create_empty(
        f"{site_id}_surface", f"{site_id} surface", 0,
        base_rect.x + base_rect.width + 2,
        base_rect.y + base_rect.height + 2,
    )

    return Site(
        id=site_id,
        kind="tower",
        buildings=[building],
        surface=surface,
        enclosure=None,
    )


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


def _flip_stair_semantics_for_tower(building: Building) -> None:
    """Swap stairs_up <-> stairs_down on every floor of the tower.

    :func:`place_cross_floor_stairs` uses dungeon conventions: the
    lower-index floor's stair feature is ``stairs_up`` because
    climbing reaches a lower ``depth``. In a tower the physical
    direction is inverted: ``floor_index + 1`` is the floor
    *above*, and the engine treats that as a ``depth`` increase
    reached by the ``descend`` action. Flipping the feature names
    on both sides of each stair link keeps the engine's floor-
    transition logic correct without special-casing towers.
    """
    swap = {"stairs_up": "stairs_down", "stairs_down": "stairs_up"}
    for floor in building.floors:
        for row in floor.tiles:
            for tile in row:
                if tile.feature in swap:
                    tile.feature = swap[tile.feature]


def _place_entry_door(
    building: Building, rng: random.Random,
) -> None:
    """Mark one ground-floor perimeter tile as ``door_closed``."""
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
        return
    dx, dy = rng.choice(sorted(candidates))
    ground.tiles[dy][dx].feature = "door_closed"

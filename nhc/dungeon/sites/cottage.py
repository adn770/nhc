"""Cottage site assembler.

See ``design/biome_features.md`` §6. A cottage is a tiny one-
building forest site with a GARDEN ring around it and no
entities in v1.
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
    EntityPlacement, Level, Rect, RectShape, RoomShape,
    SurfaceType, Terrain, Tile,
)
from nhc.dungeon.site import (
    Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.hexcrawl.model import Biome


# ── Cottage tunable constants ────────────────────────────────

COTTAGE_SURFACE_WIDTH = 14
COTTAGE_SURFACE_HEIGHT = 12
COTTAGE_BUILDING_POS = (4, 3)
COTTAGE_BUILDING_SIZE = (5, 5)
COTTAGE_GARDEN_RING = 1

# design/biome_features.md §8: three-bucket occupant roll applied
# on cottage assembly. The friendly hermit is the headline
# outcome; the hostile witch adds combat variety; abandoned
# keeps the v1 silent cottage as a plausible find.
COTTAGE_CONTENT_WEIGHTS: list[tuple[str, float]] = [
    ("hermit", 0.40),
    ("witch", 0.30),
    ("abandoned", 0.30),
]


def assemble_cottage(
    site_id: str, rng: random.Random,
    biome: Biome | None = None,
) -> Site:
    """Assemble a cottage site.

    ``biome`` is accepted for dispatcher symmetry with the other
    site assemblers; cottages are forest-only in v1 so the
    parameter is ignored for now. TODO (v2): branch on biome for
    mountain / swamp cottages once content supports them.
    """
    del biome  # unused in v1

    base_rect = Rect(
        COTTAGE_BUILDING_POS[0], COTTAGE_BUILDING_POS[1],
        COTTAGE_BUILDING_SIZE[0], COTTAGE_BUILDING_SIZE[1],
    )
    shape: RoomShape = RectShape()
    building = _build_cottage_building(
        f"{site_id}_cottage", shape, base_rect, rng,
    )

    door_xy = _place_entry_door(building, rng)
    door_map: dict[tuple[int, int], tuple[str, int, int]] = {}
    if door_xy is not None:
        neighbour = outside_neighbour(building, *door_xy)
        if neighbour is not None:
            door_map[neighbour] = (
                building.id, door_xy[0], door_xy[1],
            )
    building.validate()

    # v2 populator: roll hermit (friendly) / witch (hostile) /
    # abandoned (empty) per design/biome_features.md §8.
    _roll_cottage_content(building, rng)

    surface = _build_cottage_surface(
        f"{site_id}_surface", building,
    )

    site = Site(
        id=site_id,
        kind="cottage",
        buildings=[building],
        surface=surface,
        enclosure=None,
    )
    site.building_doors.update(door_map)
    paint_surface_doors(site, SurfaceType.GARDEN)
    return site


def _build_cottage_building(
    building_id: str, shape: RoomShape, base_rect: Rect,
    rng: random.Random,
) -> Building:
    floors, stair_links = build_floors_with_stairs(
        building_id=building_id,
        base_shape=shape,
        base_rect=base_rect,
        n_floors=1,
        descent=None,
        rng=rng,
        build_floor_fn=lambda idx, n, req: _build_cottage_floor(
            building_id, idx, shape, base_rect, n, rng,
            required_walkable=req,
        ),
    )
    floors[0].interior_floor = "wood"
    building = Building(
        id=building_id,
        base_shape=shape,
        base_rect=base_rect,
        floors=floors,
        descent=None,
        wall_material="brick",
        interior_floor="wood",
        interior_wall_material=(
            ARCHETYPE_CONFIG["cottage"].interior_wall_material
        ),
    )
    building.stair_links = stair_links
    return building


def _build_cottage_floor(
    building_id: str, floor_idx: int,
    shape: RoomShape, base_rect: Rect,
    n_floors: int, rng: random.Random,
    required_walkable: frozenset[tuple[int, int]] = frozenset(),
) -> Level:
    level = build_building_floor(
        building_id=building_id,
        floor_idx=floor_idx,
        base_shape=shape,
        base_rect=base_rect,
        n_floors=n_floors,
        rng=rng,
        archetype="cottage",
        tags=["cottage_interior"],
        required_walkable=required_walkable,
    )
    level.interior_floor = "wood"
    return level


def _roll_cottage_content(
    building: Building, rng: random.Random,
) -> None:
    """Place exactly one NPC (hermit or witch) on the cottage's
    ground-floor room centre, or leave it empty.

    Rolls from :data:`COTTAGE_CONTENT_WEIGHTS`. Uses the interior
    floor tile closest to the room centre that isn't already a
    door, so the entity never sits under the door-crossing handler
    and the player meets them face-to-face on entry.
    """
    labels, weights = zip(*COTTAGE_CONTENT_WEIGHTS)
    outcome = rng.choices(list(labels), weights=list(weights), k=1)[0]
    if outcome == "abandoned":
        return

    ground = building.ground
    room = ground.rooms[0] if ground.rooms else None
    if room is None:
        return
    rect = room.rect
    cx = rect.x + rect.width // 2
    cy = rect.y + rect.height // 2

    def _usable(x: int, y: int) -> bool:
        tile = ground.tile_at(x, y)
        return (
            tile is not None
            and tile.terrain is Terrain.FLOOR
            and tile.feature is None
        )

    if not _usable(cx, cy):
        fallback: tuple[int, int] | None = None
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                if _usable(x, y):
                    fallback = (x, y)
                    break
            if fallback is not None:
                break
        if fallback is None:
            return
        cx, cy = fallback

    ground.entities.append(EntityPlacement(
        entity_type="creature", entity_id=outcome, x=cx, y=cy,
    ))


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    """Stamp a ``door_closed`` on an interior perimeter floor tile.

    Matches the farm / town convention: perimeter floor tiles
    whose neighbour is a WALL are eligible; the door feature sits
    on the floor side so the door-crossing handler can step the
    player from the outside surface tile through the door onto
    the interior.
    """
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
    stamp_building_door(building, dx, dy)
    return (dx, dy)


def _build_cottage_surface(
    surface_id: str, building: Building,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        COTTAGE_SURFACE_WIDTH, COTTAGE_SURFACE_HEIGHT,
    )
    surface.metadata.theme = "cottage"
    surface.metadata.ambient = "forest"
    surface.metadata.prerevealed = True

    # Only the cottage footprint blocks the outdoor surface --
    # no 1-tile buffer ring.
    footprint = building.base_shape.floor_tiles(building.base_rect)
    blocked: set[tuple[int, int]] = set()
    blocked |= footprint

    garden_tiles: set[tuple[int, int]] = set()
    for (x, y) in footprint:
        for dx in range(-COTTAGE_GARDEN_RING - 1,
                        COTTAGE_GARDEN_RING + 2):
            for dy in range(-COTTAGE_GARDEN_RING - 1,
                            COTTAGE_GARDEN_RING + 2):
                ax, ay = x + dx, y + dy
                if (ax, ay) in blocked:
                    continue
                if not surface.in_bounds(ax, ay):
                    continue
                dist = max(abs(dx), abs(dy))
                if dist == COTTAGE_GARDEN_RING + 1:
                    garden_tiles.add((ax, ay))

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

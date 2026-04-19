"""Temple site assembler.

See ``design/biome_features.md`` §6. A temple is a single stone
building with a priest on the ground floor, shared across four
biomes:

- ``mountain``: octagonal stone temple with bare floor surface.
- ``forest``: rectangular stone temple with a GARDEN ring.
- ``sandlands`` / ``icelands``: mysterious variants -- octagonal
  stone with 2-4 perimeter wall tiles dropped back to VOID so
  the building reads as weathered / half-collapsed.

v1 is deliberately minimal: no descent, no enclosure, one
building. M16 will redesign temple layouts (vertical halls,
multi-stair landings); the API here is stable enough that the
swap will be a drop-in.
"""

from __future__ import annotations

import random

from nhc.dungeon.building import Building
from nhc.dungeon.generators._stairs import (
    flip_building_stair_semantics, place_cross_floor_stairs,
)
from nhc.dungeon.model import (
    EntityPlacement, Level, OctagonShape, Rect, RectShape,
    Room, RoomShape, SurfaceType, Terrain, Tile,
)
from nhc.dungeon.room_types import (
    TEMPLE_SERVICES_DEFAULT, TEMPLE_STOCK_DEFAULT,
)
from nhc.dungeon.site import (
    Site, outside_neighbour, paint_surface_doors,
    stamp_building_door,
)
from nhc.hexcrawl.model import Biome


# ── Temple tunable constants ─────────────────────────────────

TEMPLE_SURFACE_WIDTH = 22
TEMPLE_SURFACE_HEIGHT = 18
TEMPLE_BUILDING_POS = (7, 5)
TEMPLE_BUILDING_SIZE = (8, 8)
TEMPLE_GARDEN_RING = 1
TEMPLE_MYSTERIOUS_DROP_RANGE = (2, 4)


def assemble_temple(
    site_id: str, rng: random.Random,
    biome: Biome | None = None,
) -> Site:
    """Assemble a temple site.

    ``biome`` selects the variant (see module docstring). ``None``
    defaults to the forest layout so legacy call sites without a
    biome still produce a reasonable temple.
    """
    if biome is None:
        biome = Biome.FOREST

    shape: RoomShape
    if biome is Biome.FOREST:
        shape = RectShape()
    else:
        shape = OctagonShape()

    base_rect = Rect(
        TEMPLE_BUILDING_POS[0], TEMPLE_BUILDING_POS[1],
        TEMPLE_BUILDING_SIZE[0], TEMPLE_BUILDING_SIZE[1],
    )
    building = _build_temple_building(
        f"{site_id}_shrine", shape, base_rect, rng,
    )

    # Mysterious variants drop a few perimeter wall tiles back to
    # VOID. Do this BEFORE placing the door so the door is never
    # chosen on a tile that was just removed.
    if biome in (Biome.SANDLANDS, Biome.ICELANDS):
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

    # Priest placement on the ground-floor room centre. Mysterious
    # variants still get one -- but it's a hermit_priest with a
    # reduced service menu (v2 M15) rather than the full-service
    # priest. See design/biome_features.md §8.
    _place_priest(building, biome)
    _apply_mysterious_dressing(building, biome)

    surface = _build_temple_surface(
        f"{site_id}_surface", building, biome,
    )

    site = Site(
        id=site_id,
        kind="temple",
        buildings=[building],
        surface=surface,
        enclosure=None,
    )
    site.building_doors.update(door_map)
    paint_surface_doors(site, _default_surface_type(biome))
    return site


def _default_surface_type(biome: Biome) -> SurfaceType:
    if biome is Biome.FOREST:
        return SurfaceType.GARDEN
    # Mountain / sandlands / icelands temples have bare stone paths
    # approaching the shrine -- no specific surface category, the
    # Terrain.FLOOR alone carries the walkable semantics.
    return SurfaceType.NONE


def _build_temple_building(
    building_id: str, shape: RoomShape, base_rect: Rect,
    rng: random.Random,
) -> Building:
    # Single floor in v1 (M16 will redesign with vertical halls).
    ground = _build_temple_floor(building_id, 0, shape, base_rect)
    ground.interior_floor = "stone"
    building = Building(
        id=building_id,
        base_shape=shape,
        base_rect=base_rect,
        floors=[ground],
        descent=None,
        wall_material="stone",
        interior_floor="stone",
    )
    building.stair_links = place_cross_floor_stairs(building, rng)
    flip_building_stair_semantics(building)
    return building


def _build_temple_floor(
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
        tags=["temple"] + (
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
    """Pick 2-4 perimeter wall tiles and revert them to VOID.

    Skips tiles adjacent to a door candidate (no door exists yet
    when this runs, so every perimeter wall tile is eligible).
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
    lo, hi = TEMPLE_MYSTERIOUS_DROP_RANGE
    drop_count = rng.randint(lo, min(hi, len(perimeter)))
    for (x, y) in rng.sample(perimeter, drop_count):
        ground.tiles[y][x] = Tile(terrain=Terrain.VOID)


def _place_entry_door(
    building: Building, rng: random.Random,
) -> tuple[int, int] | None:
    """Stamp a ``door_closed`` on a perimeter floor tile.

    Requires the adjacent non-floor tile to still be WALL -- if
    the mysterious-variant routine already dropped that wall back
    to VOID, the interior is already "exposed" and no door is
    needed on that side.
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


MYSTERIOUS_BIOMES: frozenset[Biome] = frozenset({
    Biome.SANDLANDS, Biome.ICELANDS,
})

# Bless is the only service a mysterious-temple hermit_priest
# offers -- heal and remove_curse still require the full-service
# priest at a mountain / forest temple (design §8).
HERMIT_PRIEST_SERVICES: tuple[str, ...] = ("bless",)


def _place_priest(building: Building, biome: Biome) -> None:
    ground = building.ground
    if not ground.rooms:
        return
    room = ground.rooms[0]
    footprint = building.base_shape.floor_tiles(building.base_rect)
    cx, cy = room.rect.center
    # Octagonal footprints clip the centre slightly; snap to the
    # closest footprint tile so the priest never lands on VOID.
    if (cx, cy) not in footprint:
        cx, cy = min(
            footprint,
            key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2,
        )

    if biome in MYSTERIOUS_BIOMES:
        ground.entities.append(EntityPlacement(
            entity_type="creature", entity_id="hermit_priest",
            x=cx, y=cy,
            extra={
                "temple_services": list(HERMIT_PRIEST_SERVICES),
                "shop_stock": [],
            },
        ))
        return

    ground.entities.append(EntityPlacement(
        entity_type="creature", entity_id="priest",
        x=cx, y=cy,
        extra={
            "temple_services": list(TEMPLE_SERVICES_DEFAULT),
            "shop_stock": list(TEMPLE_STOCK_DEFAULT),
        },
    ))


def _apply_mysterious_dressing(
    building: Building, biome: Biome,
) -> None:
    """Tag the ground-floor room with a biome-specific dressing
    tag so the frontend can paint a flavour tile and look up the
    per-biome lore string.

    Icelands temples carry a ``"cursed_altar"`` tag; sandlands
    temples carry ``"buried_relic"``. Mountain / forest temples
    never get a mysterious dressing tag.
    """
    ground = building.ground
    if not ground.rooms:
        return
    room = ground.rooms[0]
    if biome is Biome.ICELANDS:
        tag = "cursed_altar"
    elif biome is Biome.SANDLANDS:
        tag = "buried_relic"
    else:
        return
    if tag not in room.tags:
        room.tags = list(room.tags) + [tag]


def _build_temple_surface(
    surface_id: str, building: Building, biome: Biome,
) -> Level:
    surface = Level.create_empty(
        surface_id, surface_id, 0,
        TEMPLE_SURFACE_WIDTH, TEMPLE_SURFACE_HEIGHT,
    )
    surface.metadata.theme = "temple"
    surface.metadata.ambient = "temple"
    surface.metadata.prerevealed = True

    footprint = building.base_shape.floor_tiles(building.base_rect)
    blocked: set[tuple[int, int]] = set()
    blocked |= footprint
    for (x, y) in footprint:
        for dx in range(-1, 2):
            for dy in range(-1, 2):
                blocked.add((x + dx, y + dy))

    garden_tiles: set[tuple[int, int]] = set()
    if biome is Biome.FOREST:
        for (x, y) in footprint:
            for dx in range(-TEMPLE_GARDEN_RING - 1,
                            TEMPLE_GARDEN_RING + 2):
                for dy in range(-TEMPLE_GARDEN_RING - 1,
                                TEMPLE_GARDEN_RING + 2):
                    ax, ay = x + dx, y + dy
                    if (ax, ay) in blocked:
                        continue
                    if not surface.in_bounds(ax, ay):
                        continue
                    dist = max(abs(dx), abs(dy))
                    if dist == TEMPLE_GARDEN_RING + 1:
                        garden_tiles.add((ax, ay))

    default_surface = _default_surface_type(biome)
    for y in range(surface.height):
        for x in range(surface.width):
            if (x, y) in blocked:
                continue
            tile = Tile(terrain=Terrain.FLOOR)
            if (x, y) in garden_tiles:
                tile.surface_type = SurfaceType.GARDEN
            else:
                tile.surface_type = default_surface
            surface.tiles[y][x] = tile
    return surface

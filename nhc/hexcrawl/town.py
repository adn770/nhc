"""Settlement town-map generator.

Produces a small single-floor :class:`Level` shaped like a town
square: five named buildings (shop, inn, temple, stable, training)
around a central courtyard, with an ``stairs_up`` entry tile the
player arrives on when they step into the settlement from the
overland.

Called by :meth:`Game.enter_hex_feature` when the player is on a
CITY or VILLAGE hex (wiring lands in M-2.3); for now the module
stands alone with a deterministic seed-reproducible layout.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import (
    EntityPlacement,
    Level,
    LevelMetadata,
    Rect,
    RectShape,
    Room,
    Terrain,
    Tile,
)
from nhc.dungeon.room_types import (
    SHOP_STOCK,
    TEMPLE_SERVICES_DEFAULT,
    TEMPLE_STOCK_DEFAULT,
)


# The five service buildings a settlement must offer. The order
# matters only for deterministic seeded placement.
REQUIRED_BUILDINGS: tuple[str, ...] = (
    "shop", "inn", "temple", "stable", "training",
)


# Fixed town map: 25 x 20, five building slots in a 3-over-2 grid,
# an entry tile at the bottom centre, and a T-shaped corridor that
# touches every room. Random seed reshuffles which building fills
# which slot -- everything else is deterministic.
_TOWN_WIDTH = 25
_TOWN_HEIGHT = 20

# Five room rectangles (the rects BELOW are Rect(x, y, w, h) so
# y=2..5 inclusive carves a 4-tall top row of rooms).
_BUILDING_SLOTS: tuple[Rect, ...] = (
    Rect(x=1, y=2, width=6, height=4),    # top-left
    Rect(x=9, y=2, width=6, height=4),    # top-centre
    Rect(x=17, y=2, width=6, height=4),   # top-right
    Rect(x=4, y=11, width=6, height=4),   # bottom-left
    Rect(x=14, y=11, width=6, height=4),  # bottom-right
)

# Corridor layout: horizontal run at y=8, vertical run at x=12
# connecting it to the entry at (12, 17). Short stubs link each
# room's doorway to the main corridor.
_MAIN_CORRIDOR_Y = 8
_MAIN_CORRIDOR_X = 12
_ENTRY = (12, 17)


def _blank_level(width: int, height: int) -> list[list[Tile]]:
    """Fill the grid with WALL tiles. VOID borders are added by
    any caller that needs them; this generator uses a fully-walled
    bounding box so the building exteriors read as solid."""
    return [
        [Tile(terrain=Terrain.WALL) for _ in range(width)]
        for _ in range(height)
    ]


def _carve_rect(tiles: list[list[Tile]], rect: Rect) -> None:
    """Mark every tile inside ``rect`` as FLOOR."""
    for y in range(rect.y, rect.y + rect.height):
        for x in range(rect.x, rect.x + rect.width):
            tiles[y][x].terrain = Terrain.FLOOR


def _carve_path(
    tiles: list[list[Tile]],
    start: tuple[int, int],
    end: tuple[int, int],
) -> None:
    """Carve an L-shaped horizontal-then-vertical path of FLOOR
    tiles between two points (inclusive)."""
    x0, y0 = start
    x1, y1 = end
    for x in range(min(x0, x1), max(x0, x1) + 1):
        tiles[y0][x].terrain = Terrain.FLOOR
    for y in range(min(y0, y1), max(y0, y1) + 1):
        tiles[y][x1].terrain = Terrain.FLOOR


def generate_town(seed: int, town_id: str = "town") -> Level:
    """Return a :class:`Level` for a settlement hex.

    Layout is fixed; the only seed-dependent choice is which of
    the five :data:`REQUIRED_BUILDINGS` occupies which slot. That
    keeps the geometry testable while each settlement still feels
    slightly different from its neighbours.
    """
    rng = random.Random(seed)
    assignments = list(REQUIRED_BUILDINGS)
    rng.shuffle(assignments)

    tiles = _blank_level(_TOWN_WIDTH, _TOWN_HEIGHT)

    # 1. Carve every building room.
    for rect in _BUILDING_SLOTS:
        _carve_rect(tiles, rect)

    # 2. Main corridor: horizontal spine across the middle.
    for x in range(2, _TOWN_WIDTH - 2):
        tiles[_MAIN_CORRIDOR_Y][x].terrain = Terrain.FLOOR

    # 3. Vertical stubs from each top room's southern edge to the
    #    main corridor.
    for rect in _BUILDING_SLOTS[:3]:
        door_x = rect.center[0]
        _carve_path(
            tiles,
            (door_x, rect.y + rect.height),
            (door_x, _MAIN_CORRIDOR_Y),
        )

    # 4. Vertical stubs from main corridor down to each bottom
    #    room's northern edge.
    for rect in _BUILDING_SLOTS[3:]:
        door_x = rect.center[0]
        _carve_path(
            tiles,
            (door_x, _MAIN_CORRIDOR_Y),
            (door_x, rect.y - 1),
        )

    # 5. Main corridor -> entry tile at bottom centre.
    _carve_path(
        tiles,
        (_MAIN_CORRIDOR_X, _MAIN_CORRIDOR_Y),
        _ENTRY,
    )

    # 6. Entry tile: stairs_up for Game.enter_hex_feature to spawn
    #    the player on.
    ex, ey = _ENTRY
    tiles[ey][ex].feature = "stairs_up"

    # 7. Build Room records, tagging each rect with its assigned
    #    building name.
    rooms: list[Room] = []
    rooms_by_tag: dict[str, Room] = {}
    for slot_idx, (rect, building) in enumerate(
        zip(_BUILDING_SLOTS, assignments),
    ):
        room = Room(
            id=f"{town_id}_room_{slot_idx}",
            rect=rect,
            shape=RectShape(),
            tags=[building],
            description=f"{building} of {town_id}",
        )
        rooms.append(room)
        rooms_by_tag[building] = room

    # 8. NPC placements: merchant in the shop, priest in the temple,
    #    recruitable adventurer in the inn. Stable and training are
    #    intentionally left unpopulated in v1 -- they exist as
    #    labelled slots ready for mounts (stable) and XP-sink
    #    services (training) to wire into later.
    entities: list[EntityPlacement] = []
    entities.append(_merchant_placement(rooms_by_tag["shop"], rng))
    entities.append(_priest_placement(rooms_by_tag["temple"]))
    entities.append(_adventurer_placement(rooms_by_tag["inn"]))
    entities.append(_innkeeper_placement(rooms_by_tag["inn"]))

    return Level(
        id=town_id,
        name=town_id,
        depth=1,
        width=_TOWN_WIDTH,
        height=_TOWN_HEIGHT,
        tiles=tiles,
        rooms=rooms,
        corridors=[],
        entities=entities,
        metadata=LevelMetadata(theme="town", ambient="town"),
    )


# ---------------------------------------------------------------------------
# NPC placement helpers (settlement services)
# ---------------------------------------------------------------------------


def _merchant_placement(room: Room, rng: random.Random) -> EntityPlacement:
    """Merchant at the shop-room centre, stocked from depth-1 pool.

    Towns reuse the dungeon shop's depth-1 :data:`SHOP_STOCK` pool
    (any procedural settlement sits at depth 1) so settlements and
    dungeon shops carry compatible wares.
    """
    pool = SHOP_STOCK[1]
    ids, weights = zip(*pool)
    count = rng.randint(4, 7)
    stock = rng.choices(list(ids), weights=list(weights), k=count)
    # Preserve order while deduping.
    seen: set[str] = set()
    unique: list[str] = []
    for iid in stock:
        if iid not in seen:
            seen.add(iid)
            unique.append(iid)
    cx, cy = room.rect.center
    return EntityPlacement(
        entity_type="creature", entity_id="merchant",
        x=cx, y=cy, extra={"shop_stock": unique},
    )


def _priest_placement(room: Room) -> EntityPlacement:
    cx, cy = room.rect.center
    return EntityPlacement(
        entity_type="creature", entity_id="priest",
        x=cx, y=cy,
        extra={
            "temple_services": list(TEMPLE_SERVICES_DEFAULT),
            "shop_stock": list(TEMPLE_STOCK_DEFAULT),
        },
    )


def _adventurer_placement(room: Room) -> EntityPlacement:
    """Hirable adventurer at the inn-room centre.

    Procedural settlements sit at depth 1, so the recruitable
    NPC is a level-1 adventurer -- matches the dungeon's depth-1
    guaranteed henchman rule (see
    :func:`nhc.dungeon.populator._place_adventurer`).
    """
    cx, cy = room.rect.center
    return EntityPlacement(
        entity_type="creature", entity_id="adventurer",
        x=cx, y=cy, extra={"adventurer_level": 1},
    )


def _innkeeper_placement(room: Room) -> EntityPlacement:
    """Innkeeper NPC offset one tile from the room's adventurer.

    The innkeeper dispenses overland rumors on a bump; placing
    them a tile east of the centre keeps the pair reachable
    without the two NPCs overlapping on the same floor tile.
    """
    cx, cy = room.rect.center
    # The inn slot is 6-wide; cx + 1 is still in-room.
    return EntityPlacement(
        entity_type="creature", entity_id="innkeeper",
        x=cx + 1, y=cy,
    )

"""Room type assignment and painting.

After BSP generates rooms and corridors, this module assigns each room
a type (standard, treasury, armory, library, crypt, shrine, garden,
trap_room) and paints its interior with appropriate contents.
"""

from __future__ import annotations

import logging
import random
from collections import Counter

logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING

from nhc.dungeon.model import EntityPlacement, Level, Rect, Room, Terrain, Tile

if TYPE_CHECKING:
    pass

# Room types that require a dead-end (1 connection)
SPECIAL_TYPES = [
    "treasury", "armory", "library", "crypt", "trap_room",
]
# Room types that can go anywhere
GENERAL_TYPES = ["shrine", "garden"]


def assign_room_types(level: Level, rng: random.Random) -> None:
    """Assign types to rooms and paint their interiors.

    Modifies room tags and places entities in-place.
    """
    # Count connections per room
    connections: dict[str, int] = {r.id: 0 for r in level.rooms}
    for corridor in level.corridors:
        for rid in corridor.connects:
            if rid in connections:
                connections[rid] += 1

    specials_placed = 0
    standard_count = 0

    for room in level.rooms:
        # Skip entry/exit — already tagged
        if "entry" in room.tags or "exit" in room.tags:
            room.tags.append("standard")
            standard_count += 1
            continue

        conn = connections.get(room.id, 0)

        # Dead-end rooms (1 connection) → high chance of special
        if conn <= 1 and specials_placed < 3:
            # Probability increases with fewer specials placed
            prob = 0.7 - specials_placed * 0.15
            if rng.random() < prob and room.rect.width >= 4 and room.rect.height >= 4:
                room_type = rng.choice(SPECIAL_TYPES)
                room.tags.append(room_type)
                _paint_room(level, room, room_type, rng)
                specials_placed += 1
                continue

        # General special rooms (any connection count)
        if rng.random() < 0.15 and specials_placed < 4:
            room_type = rng.choice(GENERAL_TYPES)
            room.tags.append(room_type)
            _paint_room(level, room, room_type, rng)
            specials_placed += 1
            continue

        # Standard or corridor-like
        if conn >= 2 or rng.random() < 0.6:
            room.tags.append("standard")
            standard_count += 1
        else:
            room.tags.append("corridor")

    # Ensure at least 3 standard rooms
    for room in level.rooms:
        if standard_count >= 3:
            break
        if "corridor" in room.tags:
            room.tags.remove("corridor")
            room.tags.append("standard")
            standard_count += 1

    tag_counts = Counter(
        t for r in level.rooms for t in r.tags
        if t not in ("entry", "exit")
    )
    logger.info("Room types assigned: %s", dict(tag_counts))


def _paint_room(
    level: Level, room, room_type: str, rng: random.Random,
) -> None:
    """Paint a specialized room's interior."""
    painters = {
        "treasury": _paint_treasury,
        "armory": _paint_armory,
        "library": _paint_library,
        "crypt": _paint_crypt,
        "shrine": _paint_shrine,
        "garden": _paint_garden,
        "trap_room": _paint_trap_room,
    }
    painter = painters.get(room_type)
    if painter:
        painter(level, room, rng)


def _random_floor(room: Room, rng: random.Random) -> tuple[int, int]:
    """Pick a random interior position within a room's floor tiles."""
    # Use shape-aware interior (exclude perimeter for better placement)
    floor = room.floor_tiles()
    perimeter = room.shape.perimeter_tiles(room.rect)
    interior = floor - perimeter
    if not interior:
        interior = floor
    if not interior:
        # Ultimate fallback for tiny rooms
        return room.rect.center
    return rng.choice(sorted(interior))


def _paint_treasury(level: Level, room: Room, rng: random.Random) -> None:
    """Gold heaps, chests, + possible mimic."""
    for _ in range(rng.randint(2, 4)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id="gold",
            x=x, y=y, extra={"dice": "4d6"},
        ))
    for _ in range(rng.randint(1, 2)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="feature", entity_id="chest",
            x=x, y=y,
        ))
    if rng.random() < 0.2:
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id="mimic", x=x, y=y,
        ))


def _paint_armory(level: Level, room: Room, rng: random.Random) -> None:
    """Weapons and armor."""
    weapons = ["dagger", "short_sword", "sword"]
    for _ in range(rng.randint(2, 3)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id=rng.choice(weapons),
            x=x, y=y,
        ))
    if rng.random() < 0.5:
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id="shield", x=x, y=y,
        ))


def _paint_library(level: Level, room: Room, rng: random.Random) -> None:
    """Scrolls."""
    scrolls = [
        "scroll_magic_missile", "scroll_sleep", "scroll_fireball",
        "scroll_lightning", "scroll_bless", "scroll_cure_wounds",
        "scroll_detect_magic", "scroll_light", "scroll_shield",
    ]
    for _ in range(rng.randint(2, 4)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id=rng.choice(scrolls),
            x=x, y=y,
        ))


def _paint_crypt(level: Level, room: Room, rng: random.Random) -> None:
    """Undead guardians + loot."""
    undead = ["skeleton", "zombie", "ghoul", "wight"]
    for _ in range(rng.randint(1, 2)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id=rng.choice(undead),
            x=x, y=y,
        ))
    x, y = _random_floor(room, rng)
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id="gold", x=x, y=y,
        extra={"dice": "3d6"},
    ))


def _paint_shrine(level: Level, room: Room, rng: random.Random) -> None:
    """Healing potion at center, water tiles around it."""
    cx, cy = room.rect.center
    floor = room.floor_tiles()
    # Small water patch around center
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            wx, wy = cx + dx, cy + dy
            if (wx, wy) in floor and level.in_bounds(wx, wy):
                tile = level.tiles[wy][wx]
                if tile.terrain == Terrain.FLOOR and not tile.feature:
                    level.tiles[wy][wx] = Tile(terrain=Terrain.WATER)
    # Healing potion on center (floor, not water)
    level.tiles[cy][cx] = Tile(terrain=Terrain.FLOOR)
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id="healing_potion", x=cx, y=cy,
    ))


def _paint_garden(level: Level, room: Room, rng: random.Random) -> None:
    """Floor with items (herbs/potions)."""
    x, y = _random_floor(room, rng)
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id="healing_potion", x=x, y=y,
    ))


def _paint_trap_room(level: Level, room: Room, rng: random.Random) -> None:
    """Dense traps with a prize."""
    for _ in range(rng.randint(2, 4)):
        x, y = _random_floor(room, rng)
        level.entities.append(EntityPlacement(
            entity_type="feature", entity_id="trap_pit",
            x=x, y=y, extra={"hidden": True},
        ))
    # Prize
    x, y = _random_floor(room, rng)
    prize = rng.choice(["sword", "shield", "scroll_fireball",
                         "scroll_haste", "healing_potion"])
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id=prize, x=x, y=y,
    ))

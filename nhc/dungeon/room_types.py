"""Room type assignment and painting.

After BSP generates rooms and corridors, this module assigns each room
a type (standard, treasury, armory, library, crypt, shrine, garden,
trap_room, shop) and paints its interior with appropriate contents.
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

# Zoo: rare, medium-sized, packed with creatures.  Requires at
# least one corridor connection �� never doorless.
ZOO_MIN_WIDTH = 5
ZOO_MIN_HEIGHT = 5
ZOO_PROBABILITY = 0.08

# Lair: 1-3 connected rooms filled with same-species humanoids.
# Surrounding rooms get reactivatable traps.
LAIR_CREATURES: dict[int, list[str]] = {
    1: ["kobold", "goblin"],
    2: ["goblin", "hobgoblin", "gnoll"],
    3: ["orc", "hobgoblin", "bugbear", "gnoll"],
    4: ["orc", "bugbear", "ogre"],
}
LAIR_PROBABILITY = 0.12
LAIR_MIN_SIZE = 4

# Nest: single room filled with vermin creatures.
NEST_CREATURES: list[str] = [
    "rat", "bat", "giant_rat", "giant_bat",
    "insect_swarm", "giant_bee",
]
NEST_PROBABILITY = 0.10
NEST_MIN_SIZE = 3

# Shop: max 1 per level, merchant + virtual stock.
SHOP_PROBABILITY = 0.20
SHOP_MIN_SIZE = 4

# Depth-tiered stock pools: (item_id, weight).
# Merchants carry a mix of consumables, gear, and tools.
SHOP_STOCK: dict[int, list[tuple[str, int]]] = {
    1: [
        ("potion_healing", 5), ("healing_bandage", 3),
        ("torch", 2), ("rations", 3),
        ("dagger", 2), ("short_sword", 2), ("shield", 1),
        ("gambeson", 1), ("leather_armor", 1),
        ("scroll_light", 2), ("scroll_magic_missile", 2),
        ("rope", 1), ("arrows", 2),
    ],
    2: [
        ("potion_healing", 5), ("potion_strength", 2),
        ("potion_speed", 2), ("rations", 2),
        ("sword", 3), ("spear", 2), ("mace", 2),
        ("brigandine", 1), ("shield", 2), ("helmet", 2),
        ("scroll_fireball", 2), ("scroll_sleep", 2),
        ("scroll_cure_wounds", 2), ("scroll_shield", 2),
        ("bow", 1), ("arrows", 2), ("lantern", 1),
    ],
    3: [
        ("potion_healing", 4), ("potion_strength", 3),
        ("potion_invisibility", 2), ("potion_speed", 2),
        ("long_sword", 2), ("war_hammer", 2), ("halberd", 2),
        ("chain_mail", 1), ("brigandine", 2), ("helmet", 2),
        ("scroll_fireball", 3), ("scroll_lightning", 2),
        ("scroll_haste", 2), ("scroll_teleportation", 1),
        ("crossbow", 1), ("arrows", 2),
    ],
    4: [
        ("potion_healing", 4), ("potion_invisibility", 3),
        ("potion_strength", 3), ("potion_speed", 2),
        ("long_sword", 2), ("war_hammer", 2),
        ("chain_mail", 2), ("plate_cuirass", 1),
        ("scroll_fireball", 2), ("scroll_lightning", 2),
        ("scroll_teleportation", 2), ("scroll_enchant_weapon", 1),
        ("scroll_enchant_armor", 1), ("scroll_haste", 2),
        ("wand_magic_missile", 1), ("wand_firebolt", 1),
    ],
}


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
    shop_placed = False

    # ── Pre-pass: assign lair (1-3 connected rooms) ──
    lair_ids: set[str] = set()
    _try_place_lair(level, connections, lair_ids, rng)
    if lair_ids:
        specials_placed += 1

    for room in level.rooms:
        # Vaults are tiny gold caches hidden off the main map —
        # leave their tags alone, they are neither standard nor
        # a special-painted type.
        if "vault" in room.tags:
            continue
        # Skip rooms already assigned as lair
        if room.id in lair_ids:
            continue
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

        # Zoo rooms — medium-sized, connected, creature-filled.
        # Rare on purpose; the "cannot be doorless" rule is
        # encoded as conn >= 1 here.
        if (conn >= 1
                and room.rect.width >= ZOO_MIN_WIDTH
                and room.rect.height >= ZOO_MIN_HEIGHT
                and specials_placed < 4
                and rng.random() < ZOO_PROBABILITY):
            room.tags.append("zoo")
            _paint_room(level, room, "zoo", rng)
            specials_placed += 1
            continue

        # Nest: single room with vermin — small rooms okay.
        if (conn >= 1
                and room.rect.width >= NEST_MIN_SIZE
                and room.rect.height >= NEST_MIN_SIZE
                and specials_placed < 5
                and rng.random() < NEST_PROBABILITY):
            room.tags.append("nest")
            _paint_room(level, room, "nest", rng)
            specials_placed += 1
            continue

        # Shop: max 1 per level, in a room with 1-2 connections.
        if (not shop_placed
                and conn >= 1 and conn <= 2
                and room.rect.width >= SHOP_MIN_SIZE
                and room.rect.height >= SHOP_MIN_SIZE
                and rng.random() < SHOP_PROBABILITY):
            room.tags.append("shop")
            _paint_room(level, room, "shop", rng)
            specials_placed += 1
            shop_placed = True
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
        "zoo": _paint_zoo,
        "nest": _paint_nest,
        "shop": _paint_shop,
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
        entity_type="item", entity_id="potion_healing", x=cx, y=cy,
    ))


def _paint_garden(level: Level, room: Room, rng: random.Random) -> None:
    """Floor with items (herbs/potions)."""
    x, y = _random_floor(room, rng)
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id="potion_healing", x=x, y=y,
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
                         "scroll_haste", "potion_healing"])
    level.entities.append(EntityPlacement(
        entity_type="item", entity_id=prize, x=x, y=y,
    ))


def _paint_shop(level: Level, room: Room, rng: random.Random) -> None:
    """Place a merchant NPC with a virtual stock of items for sale."""
    difficulty = min(max(1, level.depth), max(SHOP_STOCK.keys()))
    pool = SHOP_STOCK.get(difficulty, SHOP_STOCK[1])
    s_ids, s_weights = zip(*pool)

    count = rng.randint(4, 7)
    stock = rng.choices(list(s_ids), weights=list(s_weights), k=count)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_stock: list[str] = []
    for item_id in stock:
        if item_id not in seen:
            seen.add(item_id)
            unique_stock.append(item_id)
    stock = unique_stock

    cx, cy = room.rect.center
    level.entities.append(EntityPlacement(
        entity_type="creature", entity_id="merchant",
        x=cx, y=cy, extra={"shop_stock": stock},
    ))


def _paint_zoo(level: Level, room: Room, rng: random.Random) -> None:
    """Pack the room with creatures pulled from the depth pool.

    Uses the existing :data:`CREATURE_POOLS` so the mob mix matches
    the floor's difficulty tier.  Tries to cover roughly half of
    the room's interior floor tiles with distinct creature
    placements — enough to feel crowded without making the room
    literally wall-to-wall with bodies.
    """
    from nhc.dungeon.populator import CREATURE_POOLS

    difficulty = min(max(1, level.depth), max(CREATURE_POOLS.keys()))
    pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
    if not pool:
        return
    c_ids, c_weights = zip(*pool)

    floor = room.floor_tiles()
    perimeter = room.shape.perimeter_tiles(room.rect)
    interior = sorted(floor - perimeter)
    if len(interior) < 4:
        interior = sorted(floor)
    if not interior:
        return

    # Aim for half the interior, clamped to a sensible band so
    # tiny zoos still feel packed and huge zoos don't become
    # unwinnable.
    target = max(4, min(12, len(interior) // 2))
    rng.shuffle(interior)
    for (x, y) in interior[:target]:
        creature_id = rng.choices(
            list(c_ids), weights=list(c_weights), k=1,
        )[0]
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id=creature_id,
            x=x, y=y,
        ))


# ── Lair helpers ─────────────────────────────────────────────────────

def _try_place_lair(
    level: Level,
    connections: dict[str, int],
    lair_ids: set[str],
    rng: random.Random,
) -> None:
    """Try to place one lair of 1-3 connected rooms.

    Tags selected rooms as "lair", paints creatures, and places
    reactivatable traps in surrounding rooms.
    """
    room_map = {r.id: r for r in level.rooms}
    skip_tags = {"entry", "exit", "vault"}

    # Find candidate seed rooms
    candidates = [
        r for r in level.rooms
        if not any(t in skip_tags for t in r.tags)
        and r.rect.width >= LAIR_MIN_SIZE
        and r.rect.height >= LAIR_MIN_SIZE
        and connections.get(r.id, 0) >= 1
    ]
    if not candidates or rng.random() >= LAIR_PROBABILITY:
        return

    seed_room = rng.choice(candidates)

    # Expand to 1-3 connected rooms
    lair_rooms = [seed_room]
    max_rooms = rng.randint(1, 3)

    if max_rooms > 1:
        # Find rooms connected via corridors
        neighbors: list[Room] = []
        for corridor in level.corridors:
            if seed_room.id not in corridor.connects:
                continue
            for rid in corridor.connects:
                if rid == seed_room.id:
                    continue
                nb = room_map.get(rid)
                if (nb and not any(t in skip_tags for t in nb.tags)
                        and nb.rect.width >= LAIR_MIN_SIZE
                        and nb.rect.height >= LAIR_MIN_SIZE):
                    neighbors.append(nb)
        rng.shuffle(neighbors)
        for nb in neighbors[:max_rooms - 1]:
            if nb not in lair_rooms:
                lair_rooms.append(nb)

    # Pick creature species based on depth
    difficulty = min(max(1, level.depth), max(LAIR_CREATURES.keys()))
    species_pool = LAIR_CREATURES.get(difficulty, LAIR_CREATURES[1])
    species = rng.choice(species_pool)

    # Tag and paint each lair room
    for room in lair_rooms:
        room.tags.append("lair")
        lair_ids.add(room.id)
        _paint_lair_room(level, room, species, rng)

    # Place reactivatable traps in surrounding rooms
    _paint_lair_traps(level, lair_ids, room_map, rng)


def _paint_lair_room(
    level: Level, room: Room, species: str,
    rng: random.Random,
) -> None:
    """Fill a lair room with same-species humanoid creatures."""
    floor = room.floor_tiles()
    perimeter = room.shape.perimeter_tiles(room.rect)
    interior = sorted(floor - perimeter)
    if len(interior) < 3:
        interior = sorted(floor)
    if not interior:
        return

    target = max(3, min(8, len(interior) // 2))
    rng.shuffle(interior)
    for (x, y) in interior[:target]:
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id=species,
            x=x, y=y,
        ))

    # Loot: gold piles and food scattered around the lair
    food_items = ["rations", "bread", "dried_meat", "apple", "cheese"]
    remaining = interior[target:]  # tiles not used by creatures
    if not remaining:
        remaining = list(interior)
    rng.shuffle(remaining)

    gold_count = rng.randint(2, 4)
    for (x, y) in remaining[:gold_count]:
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id="gold",
            x=x, y=y, extra={"dice": "3d6"},
        ))

    food_count = rng.randint(1, 3)
    for (x, y) in remaining[gold_count:gold_count + food_count]:
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id=rng.choice(food_items),
            x=x, y=y,
        ))


def _paint_lair_traps(
    level: Level,
    lair_ids: set[str],
    room_map: dict[str, Room],
    rng: random.Random,
) -> None:
    """Place reactivatable traps in rooms adjacent to the lair."""
    from nhc.dungeon.populator import FEATURE_POOLS

    adjacent_ids: set[str] = set()
    for corridor in level.corridors:
        if any(rid in lair_ids for rid in corridor.connects):
            for rid in corridor.connects:
                if rid not in lair_ids and rid in room_map:
                    adj = room_map[rid]
                    skip = {"entry", "exit", "vault", "treasury",
                            "armory", "library", "crypt"}
                    if not any(t in skip for t in adj.tags):
                        adjacent_ids.add(rid)

    trap_ids, trap_weights = zip(*FEATURE_POOLS)
    for rid in adjacent_ids:
        room = room_map[rid]
        count = rng.randint(1, 3)
        for _ in range(count):
            x, y = _random_floor(room, rng)
            trap_id = rng.choices(
                list(trap_ids), weights=list(trap_weights), k=1,
            )[0]
            level.entities.append(EntityPlacement(
                entity_type="feature", entity_id=trap_id,
                x=x, y=y,
                extra={"hidden": True, "reactivatable": True},
            ))


# ── Nest painter ─────────────────────────────────────────────────────

def _paint_nest(level: Level, room: Room, rng: random.Random) -> None:
    """Fill a room with same-species vermin creatures."""
    species = rng.choice(NEST_CREATURES)

    floor = room.floor_tiles()
    perimeter = room.shape.perimeter_tiles(room.rect)
    interior = sorted(floor - perimeter)
    if len(interior) < 3:
        interior = sorted(floor)
    if not interior:
        return

    target = max(3, min(10, len(interior) // 2))
    rng.shuffle(interior)
    for (x, y) in interior[:target]:
        level.entities.append(EntityPlacement(
            entity_type="creature", entity_id=species,
            x=x, y=y,
        ))

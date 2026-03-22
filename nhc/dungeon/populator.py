"""Place creatures, items, traps, and features in generated levels."""

from __future__ import annotations

from nhc.dungeon.model import EntityPlacement, Level, Terrain
from nhc.utils.rng import get_rng

# Creature pools by difficulty tier
CREATURE_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [
        ("giant_rat", 0.15), ("goblin", 0.2), ("skeleton", 0.1),
        ("kobold", 0.1), ("giant_bee", 0.08), ("escarabat_foc", 0.08),
        ("ratpenat_gegant", 0.05), ("centpeus_gegant", 0.1),
        ("stirge", 0.07), ("cridaner", 0.07),
    ],
    2: [
        ("goblin", 0.08), ("skeleton", 0.1), ("zombie", 0.08),
        ("gnoll", 0.1), ("hobgoblin", 0.08), ("bandoler", 0.08),
        ("llop", 0.08), ("granyotic", 0.07), ("gentmalgama", 0.07),
        ("gul", 0.07), ("tarantula_gegant", 0.07), ("sangonera_gegant", 0.05),
        ("home_serp", 0.07),
    ],
    3: [
        ("orc", 0.07), ("zombie", 0.07), ("gnoll", 0.07),
        ("osgo", 0.07), ("llangardanic", 0.06), ("llop_terrible", 0.06),
        ("wight", 0.06), ("spectre", 0.04), ("basilisk", 0.04),
        ("os_negre", 0.06), ("uarg", 0.07),
        ("escorpi_gegant", 0.07), ("cocatriu", 0.06),
        ("cuc_tentacles", 0.07), ("llop_hivern", 0.07),
        ("desencantador", 0.06),
    ],
    4: [
        ("ogre", 0.06), ("os_bru", 0.06), ("uarg", 0.06),
        ("wight", 0.06), ("spectre", 0.06), ("basilisk", 0.06),
        ("llop_terrible", 0.06), ("ocell_mal_averany", 0.06),
        ("serp_gegant", 0.06), ("desencantador", 0.06),
        ("llop_hivern", 0.06),
        ("troll", 0.06), ("mummy", 0.06), ("gargoyle", 0.06),
        ("wyvern", 0.06),
        ("banshee", 0.05), ("harpy", 0.05),
    ],
}

# Item pools by difficulty tier
ITEM_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [
        ("healing_potion", 0.35), ("dagger", 0.25), ("short_sword", 0.15),
        ("scroll_sleep", 0.1), ("scroll_cure_wounds", 0.1),
        ("scroll_bless", 0.05),
    ],
    2: [
        ("healing_potion", 0.2), ("short_sword", 0.15), ("sword", 0.1),
        ("scroll_lightning", 0.1), ("scroll_magic_missile", 0.1),
        ("scroll_sleep", 0.08), ("scroll_cure_wounds", 0.08),
        ("scroll_web", 0.07), ("scroll_bless", 0.07),
        ("scroll_mirror_image", 0.05),
    ],
    3: [
        ("healing_potion", 0.15), ("sword", 0.1), ("shield", 0.1),
        ("scroll_lightning", 0.08), ("scroll_magic_missile", 0.08),
        ("scroll_hold_person", 0.1), ("scroll_fireball", 0.1),
        ("scroll_charm_person", 0.07), ("scroll_haste", 0.07),
        ("scroll_invisibility", 0.07), ("scroll_protection_evil", 0.08),
    ],
    4: [
        ("healing_potion", 0.1), ("sword", 0.08), ("shield", 0.08),
        ("scroll_fireball", 0.1), ("scroll_hold_person", 0.1),
        ("scroll_haste", 0.1), ("scroll_invisibility", 0.1),
        ("scroll_mirror_image", 0.1), ("scroll_charm_person", 0.1),
        ("scroll_protection_evil", 0.14),
    ],
}

# Feature pools
FEATURE_POOLS: list[tuple[str, float]] = [
    ("trap_pit", 1.0),
]


def populate_level(
    level: Level,
    creature_count: int = 3,
    item_count: int = 2,
    trap_count: int = 1,
) -> None:
    """Place entities in a generated level's rooms.

    Modifies level.entities in place. Avoids placing on stairs
    or in the first room (player spawn).
    """
    rng = get_rng()
    difficulty = min(max(1, level.depth), max(CREATURE_POOLS.keys()))

    # Gather valid rooms (skip first room — player spawn)
    placeable_rooms = level.rooms[1:] if len(level.rooms) > 1 else []
    if not placeable_rooms:
        return

    def _random_floor_in_room(room_idx: int) -> tuple[int, int] | None:
        """Pick a random walkable tile in a room, avoiding features."""
        room = placeable_rooms[room_idx]
        rect = room.rect
        candidates = []
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                tile = level.tile_at(x, y)
                if tile and tile.terrain == Terrain.FLOOR and not tile.feature:
                    candidates.append((x, y))
        if not candidates:
            return None
        return rng.choice(candidates)

    occupied: set[tuple[int, int]] = set()

    def _place_unique(room_idx: int) -> tuple[int, int] | None:
        pos = _random_floor_in_room(room_idx)
        if pos and pos not in occupied:
            occupied.add(pos)
            return pos
        return None

    # Place creatures
    c_pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
    c_ids, c_weights = zip(*c_pool) if c_pool else ([], [])
    for _ in range(creature_count):
        room_idx = rng.randint(0, len(placeable_rooms) - 1)
        pos = _place_unique(room_idx)
        if not pos:
            continue
        creature_id = rng.choices(list(c_ids), weights=list(c_weights), k=1)[0]
        level.entities.append(EntityPlacement(
            entity_type="creature",
            entity_id=creature_id,
            x=pos[0], y=pos[1],
        ))

    # Place items
    i_pool = ITEM_POOLS.get(difficulty, ITEM_POOLS[1])
    i_ids, i_weights = zip(*i_pool) if i_pool else ([], [])
    for _ in range(item_count):
        room_idx = rng.randint(0, len(placeable_rooms) - 1)
        pos = _place_unique(room_idx)
        if not pos:
            continue
        item_id = rng.choices(list(i_ids), weights=list(i_weights), k=1)[0]
        level.entities.append(EntityPlacement(
            entity_type="item",
            entity_id=item_id,
            x=pos[0], y=pos[1],
        ))

    # Place traps
    for _ in range(trap_count):
        room_idx = rng.randint(0, len(placeable_rooms) - 1)
        pos = _place_unique(room_idx)
        if not pos:
            continue
        feat_id, _ = rng.choice(FEATURE_POOLS)
        level.entities.append(EntityPlacement(
            entity_type="feature",
            entity_id=feat_id,
            x=pos[0], y=pos[1],
            extra={"hidden": True},
        ))

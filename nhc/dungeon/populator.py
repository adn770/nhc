"""Place creatures, items, traps, and features in generated levels."""

from __future__ import annotations

from nhc.dungeon.model import EntityPlacement, Level, Terrain
from nhc.utils.rng import get_rng

# Creature pools by difficulty tier
CREATURE_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [("goblin", 0.6), ("skeleton", 0.4)],
    2: [("goblin", 0.3), ("skeleton", 0.7)],
}

# Item pools by difficulty tier
ITEM_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [("healing_potion", 0.5), ("dagger", 0.3), ("short_sword", 0.2)],
    2: [("healing_potion", 0.4), ("short_sword", 0.3), ("sword", 0.3)],
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
    difficulty = min(level.depth, max(CREATURE_POOLS.keys()))

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

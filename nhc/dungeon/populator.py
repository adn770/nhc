"""Place creatures, items, traps, and features in generated levels.

Uses difficulty-tiered pools and encounter groups for more varied
and tactically interesting dungeon populations.
"""

from __future__ import annotations

import random

from nhc.dungeon.model import EntityPlacement, Level, Terrain
from nhc.utils.rng import get_rng

# ── Creature pools by difficulty tier ────────────────────────────────

CREATURE_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [
        ("giant_rat", 0.15), ("rat", 0.10), ("goblin", 0.20),
        ("skeleton", 0.10), ("kobold", 0.10), ("giant_bee", 0.08),
        ("bat", 0.08), ("giant_centipede", 0.10), ("stirge", 0.09),
    ],
    2: [
        ("goblin", 0.08), ("skeleton", 0.10), ("zombie", 0.08),
        ("gnoll", 0.10), ("hobgoblin", 0.08), ("bandit", 0.08),
        ("wolf", 0.08), ("frogman", 0.07), ("amalgamkin", 0.07),
        ("ghoul", 0.07), ("giant_tarantula", 0.07),
        ("giant_leech", 0.05), ("snakeman", 0.07),
    ],
    3: [
        ("orc", 0.07), ("zombie", 0.07), ("gnoll", 0.07),
        ("bugbear", 0.07), ("lizardman", 0.06), ("dire_wolf", 0.06),
        ("wight", 0.06), ("spectre", 0.04), ("basilisk", 0.04),
        ("black_bear", 0.06), ("warg", 0.07),
        ("giant_scorpion", 0.07), ("cockatrice", 0.06),
        ("tentacle_worm", 0.07), ("winter_wolf", 0.07),
        ("disenchanter", 0.06),
    ],
    4: [
        ("ogre", 0.06), ("brown_bear", 0.06), ("warg", 0.06),
        ("wight", 0.06), ("spectre", 0.06), ("basilisk", 0.06),
        ("dire_wolf", 0.06), ("ill_omen_bird", 0.06),
        ("giant_snake", 0.06), ("disenchanter", 0.06),
        ("winter_wolf", 0.06), ("troll", 0.06), ("mummy", 0.06),
        ("gargoyle", 0.06), ("wyvern", 0.06),
        ("banshee", 0.05), ("harpy", 0.05),
    ],
}

# ── Encounter group templates ────────────────────────────────────────

ENCOUNTER_GROUPS: list[tuple[str, int, int]] = [
    # (pattern, min_size, max_size)
    ("solo", 1, 1),
    ("pair", 2, 2),
    ("pack", 3, 4),
]

# ── Item pools by difficulty tier ────────────────────────────────────

ITEM_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [
        ("healing_potion", 0.15), ("potion_purification", 0.03),
        ("dagger", 0.10), ("club", 0.08), ("short_sword", 0.08),
        ("sling", 0.05), ("gambeson", 0.05), ("shield", 0.05),
        ("torch", 0.05), ("rope", 0.04), ("rations", 0.08),
        ("bread", 0.06), ("apple", 0.05), ("cheese", 0.04),
        ("scroll_sleep", 0.06), ("scroll_cure_wounds", 0.06),
        ("scroll_bless", 0.04), ("potion_frost", 0.04),
        ("potion_mind_vision", 0.03), ("lockpicks", 0.03),
        ("crowbar", 0.02), ("pick", 0.02),
        ("scroll_detect_gold", 0.03), ("scroll_detect_food", 0.03),
    ],
    2: [
        ("healing_potion", 0.10), ("potion_frost", 0.04),
        ("rations", 0.06), ("dried_meat", 0.05),
        ("bread", 0.04), ("mushroom", 0.04),
        ("potion_strength", 0.03), ("potion_invisibility", 0.03),
        ("short_sword", 0.07), ("sword", 0.06), ("spear", 0.05),
        ("mace", 0.05), ("axe", 0.04), ("bow", 0.04),
        ("brigantine", 0.03), ("helmet", 0.03), ("shield", 0.04),
        ("scroll_lightning", 0.06), ("scroll_magic_missile", 0.06),
        ("scroll_sleep", 0.05), ("scroll_cure_wounds", 0.05),
        ("scroll_web", 0.04), ("scroll_bless", 0.04),
        ("scroll_mirror_image", 0.03), ("potion_mind_vision", 0.03),
        ("lantern", 0.03), ("scroll_identify", 0.03),
        ("pickaxe", 0.02),
        ("scroll_detect_gold", 0.02), ("scroll_detect_food", 0.02),
    ],
    3: [
        ("healing_potion", 0.12), ("sword", 0.08), ("shield", 0.08),
        ("rations", 0.05), ("dried_meat", 0.04),
        ("mushroom", 0.04), ("cheese", 0.03),
        ("scroll_lightning", 0.07), ("scroll_magic_missile", 0.07),
        ("scroll_hold_person", 0.08), ("scroll_fireball", 0.08),
        ("scroll_charm_person", 0.06), ("scroll_haste", 0.06),
        ("scroll_invisibility", 0.06), ("scroll_protection_evil", 0.07),
        ("wand_magic_missile", 0.03), ("wand_firebolt", 0.02),
        ("ring_protection", 0.02), ("ring_mending", 0.02),
        ("wand_poison", 0.02), ("potion_strength", 0.04),
        ("sword_plus_1", 0.02), ("dagger_plus_1", 0.02),
        ("shield_plus_1", 0.02), ("gambeson_plus_1", 0.02),
        ("pickaxe", 0.03), ("mattock", 0.02),
    ],
    4: [
        ("healing_potion", 0.06), ("sword", 0.03), ("shield", 0.03),
        ("rations", 0.04), ("dried_meat", 0.03), ("mushroom", 0.03),
        ("scroll_fireball", 0.07), ("scroll_hold_person", 0.07),
        ("scroll_haste", 0.07), ("scroll_invisibility", 0.07),
        ("scroll_mirror_image", 0.06), ("scroll_charm_person", 0.06),
        ("scroll_protection_evil", 0.08),
        ("wand_firebolt", 0.03), ("wand_lightning", 0.03),
        ("wand_disintegrate", 0.02), ("wand_teleport", 0.02),
        ("ring_haste", 0.02), ("ring_evasion", 0.02),
        ("ring_elements", 0.02), ("ring_accuracy", 0.02),
        ("ring_shadows", 0.02), ("ring_detection", 0.02),
        ("wand_amok", 0.02),
        ("sword_plus_1", 0.03), ("axe_plus_1", 0.02),
        ("mace_plus_1", 0.02), ("long_sword_plus_1", 0.01),
        ("spear_plus_1", 0.02), ("war_hammer_plus_1", 0.01),
        ("bow_plus_1", 0.01), ("crossbow_plus_1", 0.01),
        ("brigantine_plus_1", 0.02), ("chain_mail_plus_1", 0.01),
        ("shield_plus_1", 0.02), ("helmet_plus_1", 0.02),
        ("mattock", 0.03),
    ],
}

# ── Feature/trap pools ───────────────────────────────────────────────

FEATURE_POOLS: list[tuple[str, float]] = [
    ("trap_pit", 0.12),
    ("trap_fire", 0.10),
    ("trap_poison", 0.10),
    ("trap_paralysis", 0.08),
    ("trap_alarm", 0.07),
    ("trap_teleport", 0.07),
    ("trap_summoning", 0.06),
    ("trap_gripping", 0.08),
    ("trap_arrow", 0.10),
    ("trap_darts", 0.08),
    ("trap_falling_stone", 0.07),
    ("trap_spores", 0.07),
    ("trap_trapdoor", 0.05),
]

# ── Buried item pools (gold + potions by tier) ─────────────────────

BURIED_POOLS: dict[int, list[tuple[str, float]]] = {
    1: [("gold", 0.52), ("healing_potion", 0.25),
        ("potion_purification", 0.10),
        ("gem_garnet", 0.02), ("gem_topaz", 0.01),
        ("glass_piece_1", 0.04), ("glass_piece_2", 0.02),
        ("glass_piece_3", 0.02), ("glass_piece_4", 0.02)],
    2: [("gold", 0.42), ("healing_potion", 0.25),
        ("potion_strength", 0.10), ("potion_frost", 0.10),
        ("gem_garnet", 0.02), ("gem_topaz", 0.01),
        ("glass_piece_5", 0.04), ("glass_piece_6", 0.02),
        ("glass_piece_7", 0.02), ("glass_piece_8", 0.02)],
    3: [("gold", 0.34), ("healing_potion", 0.20),
        ("potion_strength", 0.12), ("potion_frost", 0.12),
        ("gem_amethyst", 0.02), ("gem_opal", 0.02),
        ("gem_topaz", 0.02),
        ("glass_piece_1", 0.04), ("glass_piece_2", 0.04),
        ("glass_piece_3", 0.04), ("glass_piece_4", 0.04)],
    4: [("gold", 0.25), ("healing_potion", 0.15),
        ("potion_strength", 0.08), ("potion_invisibility", 0.08),
        ("potion_frost", 0.08),
        ("gem_ruby", 0.03), ("gem_emerald", 0.02),
        ("gem_sapphire", 0.02), ("gem_diamond", 0.01),
        ("gem_amethyst", 0.02),
        ("glass_piece_5", 0.06), ("glass_piece_6", 0.04),
        ("glass_piece_7", 0.04), ("glass_piece_8", 0.04),
        ("glass_piece_1", 0.04), ("glass_piece_2", 0.04)],
}


def _place_adventurer(
    level: Level,
    placeable: list,
    occupied: set[tuple[int, int]],
    rng: "random.Random",
) -> None:
    """Maybe place a recruitable adventurer in an eligible room.

    ~15% chance per eligible room, max 1 per floor.
    """
    excluded_tags = {"shop", "vault", "exit", "lair", "nest", "zoo"}
    eligible = [r for r in placeable
                if not any(t in excluded_tags for t in r.tags)]
    if not eligible:
        return
    rng.shuffle(eligible)
    for room in eligible:
        if rng.random() > 0.15:
            continue
        rect = room.rect
        candidates = []
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                tile = level.tile_at(x, y)
                if (tile and tile.terrain == Terrain.FLOOR
                        and not tile.feature
                        and (x, y) not in occupied):
                    candidates.append((x, y))
        if not candidates:
            continue
        ax, ay = rng.choice(candidates)
        adv_level = max(1, level.depth // 2)
        level.entities.append(EntityPlacement(
            entity_type="creature",
            entity_id="adventurer",
            x=ax, y=ay,
            extra={"adventurer_level": adv_level},
        ))
        occupied.add((ax, ay))
        return  # max 1 per floor


def _bury_items(
    level: Level,
    rng: "random.Random",
) -> None:
    """Bury gold and potions in random floor tiles."""
    difficulty = min(max(1, level.depth), max(BURIED_POOLS.keys()))
    pool = BURIED_POOLS.get(difficulty, BURIED_POOLS[1])
    b_ids, b_weights = zip(*pool)

    # Scale count with depth
    count = 2 + level.depth // 2 + rng.randint(0, 2)

    placeable = [r for r in level.rooms
                 if "entry" not in r.tags
                 and r.rect.width >= 3 and r.rect.height >= 3]
    if not placeable:
        return

    for _ in range(count):
        room = rng.choice(placeable)
        rect = room.rect
        candidates = []
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                tile = level.tile_at(x, y)
                if (tile and tile.terrain == Terrain.FLOOR
                        and not tile.feature and not tile.buried):
                    candidates.append((x, y))
        if not candidates:
            continue
        bx, by = rng.choice(candidates)
        item_id = rng.choices(list(b_ids), weights=list(b_weights), k=1)[0]
        level.tile_at(bx, by).buried.append(item_id)


def _find_single_tile_corridors(level: Level) -> list[tuple[int, int]]:
    """Find corridor tiles that form segments of exactly one tile."""
    corridor_tiles: set[tuple[int, int]] = set()
    for y in range(level.height):
        for x in range(level.width):
            t = level.tiles[y][x]
            if t.terrain == Terrain.FLOOR and t.is_corridor:
                corridor_tiles.add((x, y))

    # Flood-fill into connected segments
    visited: set[tuple[int, int]] = set()
    singles: list[tuple[int, int]] = []
    for start in sorted(corridor_tiles):
        if start in visited:
            continue
        segment: list[tuple[int, int]] = []
        queue = [start]
        while queue:
            pos = queue.pop()
            if pos in visited:
                continue
            visited.add(pos)
            segment.append(pos)
            x, y = pos
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nb = (x + dx, y + dy)
                if nb in corridor_tiles and nb not in visited:
                    queue.append(nb)
        if len(segment) == 1:
            singles.append(segment[0])
    return singles


def _populate_single_tile_corridors(
    level: Level,
    difficulty: int,
    occupied: set[tuple[int, int]],
    rng,
) -> None:
    """Place a creature or item on single-tile corridor segments.

    Distribution: 50% nothing, 30% creature, 20% item.
    """
    singles = _find_single_tile_corridors(level)
    if not singles:
        return

    c_pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
    c_ids, c_weights = zip(*c_pool) if c_pool else ([], [])
    i_pool = ITEM_POOLS.get(difficulty, ITEM_POOLS[1])
    i_ids, i_weights = zip(*i_pool) if i_pool else ([], [])

    for x, y in singles:
        if (x, y) in occupied:
            continue
        tile = level.tile_at(x, y)
        if tile and tile.feature:
            continue

        roll = rng.random()
        if roll < 0.50:
            continue  # nothing
        elif roll < 0.80:
            # creature (30%)
            if c_ids:
                cid = rng.choices(
                    list(c_ids), weights=list(c_weights), k=1)[0]
                level.entities.append(EntityPlacement(
                    entity_type="creature", entity_id=cid,
                    x=x, y=y,
                ))
                occupied.add((x, y))
        else:
            # item (20%)
            if i_ids:
                iid = rng.choices(
                    list(i_ids), weights=list(i_weights), k=1)[0]
                level.entities.append(EntityPlacement(
                    entity_type="item", entity_id=iid,
                    x=x, y=y,
                ))
                occupied.add((x, y))


def populate_level(
    level: Level,
    creature_count: int | None = None,
    item_count: int | None = None,
    trap_count: int | None = None,
    rng: "random.Random | None" = None,
) -> None:
    """Place entities in a generated level's rooms.

    Counts scale with depth if not explicitly provided.
    Modifies level.entities in place.
    """
    rng = rng or get_rng()
    difficulty = min(max(1, level.depth), max(CREATURE_POOLS.keys()))

    # Scale counts with depth
    if creature_count is None:
        creature_count = 2 + level.depth + rng.randint(0, 2)
    if item_count is None:
        item_count = 3 + rng.randint(0, level.depth)
    if trap_count is None:
        trap_count = max(0, level.depth - 1) + rng.randint(0, 1)

    # Gather valid rooms (skip entry room — player spawn)
    placeable = [r for r in level.rooms
                 if "entry" not in r.tags
                 and r.rect.width >= 3 and r.rect.height >= 3]
    # Also skip rooms already populated by room_types painters
    special_tags = {"treasury", "armory", "library", "crypt",
                    "trap_room", "shrine", "garden", "zoo",
                    "lair", "nest", "shop"}
    combat_rooms = [r for r in placeable
                    if not any(t in special_tags for t in r.tags)]

    if not combat_rooms:
        combat_rooms = placeable
    # Last resort: include all rooms (even entry) so the
    # level is never completely empty of creatures.
    if not combat_rooms:
        combat_rooms = [r for r in level.rooms
                        if r.rect.width >= 3 and r.rect.height >= 3]
    if not combat_rooms:
        return

    occupied: set[tuple[int, int]] = set()

    def _pick_floor(room) -> tuple[int, int] | None:
        rect = room.rect
        candidates = []
        for y in range(rect.y, rect.y2):
            for x in range(rect.x, rect.x2):
                tile = level.tile_at(x, y)
                if (tile and tile.terrain == Terrain.FLOOR
                        and not tile.feature
                        and (x, y) not in occupied):
                    candidates.append((x, y))
        if not candidates:
            return None
        pos = rng.choice(candidates)
        occupied.add(pos)
        return pos

    # ── Place creature encounters ──
    MIN_CREATURES = 3
    c_pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
    c_ids, c_weights = zip(*c_pool) if c_pool else ([], [])
    remaining = creature_count
    max_attempts = creature_count * 3  # prevent infinite loop

    while remaining > 0 and combat_rooms and max_attempts > 0:
        max_attempts -= 1
        room = rng.choice(combat_rooms)

        # Pick encounter size
        group = rng.choice(ENCOUNTER_GROUPS)
        _, gmin, gmax = group
        size = min(rng.randint(gmin, gmax), remaining)

        # Pick creature type for the group
        creature_id = rng.choices(list(c_ids), weights=list(c_weights), k=1)[0]

        for _ in range(size):
            pos = _pick_floor(room)
            if not pos:
                break
            level.entities.append(EntityPlacement(
                entity_type="creature", entity_id=creature_id,
                x=pos[0], y=pos[1],
            ))
            remaining -= 1

    # Guarantee a minimum number of creatures even if the main
    # loop ran out of attempts (small maps with few open tiles).
    placed = sum(1 for e in level.entities
                 if e.entity_type == "creature")
    if placed < MIN_CREATURES and c_ids:
        all_rooms = combat_rooms or placeable or level.rooms
        for _ in range(MIN_CREATURES - placed):
            room = rng.choice(all_rooms)
            pos = _pick_floor(room)
            if not pos:
                continue
            creature_id = rng.choices(
                list(c_ids), weights=list(c_weights), k=1)[0]
            level.entities.append(EntityPlacement(
                entity_type="creature", entity_id=creature_id,
                x=pos[0], y=pos[1],
            ))

    # ── Place items ──
    i_pool = ITEM_POOLS.get(difficulty, ITEM_POOLS[1])
    i_ids, i_weights = zip(*i_pool) if i_pool else ([], [])
    all_rooms = [r for r in placeable
                 if not any(t in {"treasury", "armory", "library"}
                            for t in r.tags)]
    if not all_rooms:
        all_rooms = placeable

    for _ in range(item_count):
        if not all_rooms:
            break
        room = rng.choice(all_rooms)
        pos = _pick_floor(room)
        if not pos:
            continue
        item_id = rng.choices(list(i_ids), weights=list(i_weights), k=1)[0]
        level.entities.append(EntityPlacement(
            entity_type="item", entity_id=item_id,
            x=pos[0], y=pos[1],
        ))

    # ── Guarantee a digging tool on levels 1-5 ──
    if level.depth <= 5:
        digging_tools = ["pick", "shovel", "pickaxe", "mattock"]
        tool_rooms = list(all_rooms or placeable)
        rng.shuffle(tool_rooms)
        for room in tool_rooms:
            pos = _pick_floor(room)
            if pos:
                tool_id = rng.choice(digging_tools)
                level.entities.append(EntityPlacement(
                    entity_type="item", entity_id=tool_id,
                    x=pos[0], y=pos[1],
                ))
                break

    # ── Place gold ──
    gold_dice = f"{2 + level.depth}d8"
    gold_count = rng.randint(2, 3 + level.depth)
    for _ in range(gold_count):
        if not placeable:
            break
        room = rng.choice(placeable)
        pos = _pick_floor(room)
        if pos:
            level.entities.append(EntityPlacement(
                entity_type="item", entity_id="gold",
                x=pos[0], y=pos[1],
                extra={"gold_dice": gold_dice},
            ))

    # ── Place chests ──
    chest_count = rng.randint(0, 1 + level.depth // 2)
    for _ in range(chest_count):
        if not placeable:
            break
        room = rng.choice(placeable)
        pos = _pick_floor(room)
        if pos:
            level.entities.append(EntityPlacement(
                entity_type="feature", entity_id="chest",
                x=pos[0], y=pos[1],
            ))

    # ── Place barrels and crates ──
    container_count = rng.randint(1, 2 + level.depth // 3)
    container_types = ["barrel", "crate"]
    for _ in range(container_count):
        if not placeable:
            break
        room = rng.choice(placeable)
        pos = _pick_floor(room)
        if pos:
            ctype = rng.choice(container_types)
            level.entities.append(EntityPlacement(
                entity_type="feature", entity_id=ctype,
                x=pos[0], y=pos[1],
            ))

    # ── Place traps ──
    for _ in range(trap_count):
        if not combat_rooms:
            break
        room = rng.choice(combat_rooms)
        pos = _pick_floor(room)
        if not pos:
            continue
        feat_id, _ = rng.choice(FEATURE_POOLS)
        level.entities.append(EntityPlacement(
            entity_type="feature", entity_id=feat_id,
            x=pos[0], y=pos[1],
            extra={"hidden": True},
        ))

    # ── Place entities on single-tile corridor segments ──
    # 50% nothing, 30% creature, 20% item
    _populate_single_tile_corridors(level, difficulty, occupied, rng)

    # ── Fill vault rooms with gold ──
    # Vaults are tiny disconnected caches; every floor tile gets a
    # gold pile so breaking in is always worth the dig.  Normal
    # creature/item placement already skips them via the w>=3
    # size filter, so we don't need to clean up other entities.
    for room in level.rooms:
        if "vault" not in room.tags:
            continue
        for (vx, vy) in sorted(room.floor_tiles()):
            tile = level.tile_at(vx, vy)
            if not tile or tile.terrain != Terrain.FLOOR:
                continue
            vault_dice = f"{3 * level.depth}d12"
            level.entities.append(EntityPlacement(
                entity_type="item", entity_id="gold",
                x=vx, y=vy,
                extra={"gold_dice": vault_dice},
            ))
            occupied.add((vx, vy))

    # ── Place an adventurer (recruitable henchman) ──
    _place_adventurer(level, placeable, occupied, rng)

    # ── Bury hidden items in floor tiles ──
    _bury_items(level, rng)

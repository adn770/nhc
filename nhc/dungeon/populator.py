"""Place creatures, items, traps, and features in generated levels.

Uses difficulty-tiered pools and encounter groups for more varied
and tactically interesting dungeon populations.
"""

from __future__ import annotations

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
        ("torch", 0.05), ("rope", 0.04), ("rations", 0.04),
        ("scroll_sleep", 0.06), ("scroll_cure_wounds", 0.06),
        ("scroll_bless", 0.04), ("potion_frost", 0.04),
        ("potion_mind_vision", 0.03), ("lockpicks", 0.03),
        ("crowbar", 0.02),
    ],
    2: [
        ("healing_potion", 0.10), ("potion_frost", 0.04),
        ("potion_strength", 0.03), ("potion_invisibility", 0.03),
        ("short_sword", 0.07), ("sword", 0.06), ("spear", 0.05),
        ("mace", 0.05), ("axe", 0.04), ("bow", 0.04),
        ("brigantine", 0.03), ("helmet", 0.03), ("shield", 0.04),
        ("scroll_lightning", 0.06), ("scroll_magic_missile", 0.06),
        ("scroll_sleep", 0.05), ("scroll_cure_wounds", 0.05),
        ("scroll_web", 0.04), ("scroll_bless", 0.04),
        ("scroll_mirror_image", 0.03), ("potion_mind_vision", 0.03),
        ("lantern", 0.03), ("scroll_identify", 0.03),
    ],
    3: [
        ("healing_potion", 0.12), ("sword", 0.08), ("shield", 0.08),
        ("scroll_lightning", 0.07), ("scroll_magic_missile", 0.07),
        ("scroll_hold_person", 0.08), ("scroll_fireball", 0.08),
        ("scroll_charm_person", 0.06), ("scroll_haste", 0.06),
        ("scroll_invisibility", 0.06), ("scroll_protection_evil", 0.07),
        ("wand_magic_missile", 0.03), ("wand_firebolt", 0.02),
        ("ring_protection", 0.02), ("ring_mending", 0.02),
        ("wand_poison", 0.02), ("potion_strength", 0.04),
        ("sword_plus_1", 0.02), ("dagger_plus_1", 0.02),
        ("shield_plus_1", 0.02), ("gambeson_plus_1", 0.02),
    ],
    4: [
        ("healing_potion", 0.06), ("sword", 0.03), ("shield", 0.03),
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
]


def populate_level(
    level: Level,
    creature_count: int | None = None,
    item_count: int | None = None,
    trap_count: int | None = None,
) -> None:
    """Place entities in a generated level's rooms.

    Counts scale with depth if not explicitly provided.
    Modifies level.entities in place.
    """
    rng = get_rng()
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
                    "trap_room", "shrine", "garden"}
    combat_rooms = [r for r in placeable
                    if not any(t in special_tags for t in r.tags)]

    if not combat_rooms:
        combat_rooms = placeable
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
    c_pool = CREATURE_POOLS.get(difficulty, CREATURE_POOLS[1])
    c_ids, c_weights = zip(*c_pool) if c_pool else ([], [])
    remaining = creature_count

    while remaining > 0 and combat_rooms:
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

    # ── Place gold ──
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

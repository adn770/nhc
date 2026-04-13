"""Item price table for shop transactions.

Prices are in gold pieces, loosely based on Knave copper prices
divided by 10 and rounded.  Enchanted (+1) items cost roughly
triple the base price.
"""

from __future__ import annotations

# fmt: off
ITEM_PRICES: dict[str, int] = {
    # --- Weapons (melee, d6 tier) ---
    "dagger":              5,
    "club":                5,
    "staff":               5,
    "silver_dagger":       30,
    # --- Weapons (melee, d8 tier) ---
    "short_sword":         10,
    "sword":               10,
    "spear":               10,
    "mace":                10,
    "axe":                 10,
    "hand_axe":            10,
    # --- Weapons (melee, d10 tier) ---
    "long_sword":          20,
    "halberd":             20,
    "war_hammer":          20,
    # --- Ranged ---
    "sling":               5,
    "bow":                 15,
    "crossbow":            60,
    "javelin":             10,
    "arrows":              5,
    # --- Enchanted weapons (+1) ---
    "dagger_plus_1":       15,
    "club_plus_1":         15,
    "staff_plus_1":        15,
    "short_sword_plus_1":  30,
    "sword_plus_1":        30,
    "spear_plus_1":        30,
    "mace_plus_1":         30,
    "axe_plus_1":          30,
    "hand_axe_plus_1":     30,
    "long_sword_plus_1":   60,
    "halberd_plus_1":      60,
    "war_hammer_plus_1":   60,
    "sling_plus_1":        15,
    "bow_plus_1":          45,
    "crossbow_plus_1":     180,
    # --- Armor ---
    "gambeson":            6,
    "brigandine":          50,
    "chain_mail":          120,
    "plate_cuirass":       400,
    "full_plate":          800,
    "shield":              40,
    "helmet":              40,
    "leather_armor":       20,
    # --- Enchanted armor (+1) ---
    "gambeson_plus_1":     18,
    "brigandine_plus_1":   150,
    "chain_mail_plus_1":   360,
    "plate_cuirass_plus_1": 1200,
    "full_plate_plus_1":   2400,
    "shield_plus_1":       120,
    "helmet_plus_1":       120,
    "leather_armor_plus_1": 60,
    # --- Potions ---
    "potion_healing":      50,
    "potion_strength":     75,
    "potion_speed":        75,
    "potion_invisibility": 100,
    "potion_levitation":   75,
    "potion_frost":        50,
    "potion_mind_vision":  75,
    "potion_purification": 50,
    "potion_acid":         40,
    "potion_liquid_flame": 40,
    "potion_blindness":    25,
    "potion_confusion":    25,
    "potion_sickness":     25,
    "potion_paralytic_gas": 25,
    # --- Scrolls ---
    "scroll_magic_missile": 50,
    "scroll_sleep":         50,
    "scroll_fireball":      100,
    "scroll_lightning":     100,
    "scroll_shield":        50,
    "scroll_mirror_image":  75,
    "scroll_haste":         75,
    "scroll_fly":           75,
    "scroll_invisibility":  100,
    "scroll_levitate":      50,
    "scroll_light":         25,
    "scroll_hold_person":   75,
    "scroll_charm_person":  75,
    "scroll_charm_snakes":  50,
    "scroll_silence":       50,
    "scroll_web":           50,
    "scroll_phantasmal_force": 75,
    "scroll_teleportation": 100,
    "scroll_water_breathing": 50,
    "scroll_bless":         50,
    "scroll_cure_wounds":   50,
    "scroll_remove_fear":   25,
    "scroll_identify":      50,
    "scroll_detect_magic":  25,
    "scroll_detect_evil":   25,
    "scroll_detect_food":   25,
    "scroll_detect_gems":   50,
    "scroll_detect_gold":   25,
    "scroll_detect_invisibility": 50,
    "scroll_reveal_map":    100,
    "scroll_find_traps":    50,
    "scroll_clairvoyance":  75,
    "scroll_infravision":   50,
    "scroll_dispel_magic":  75,
    "scroll_enchant_weapon": 200,
    "scroll_enchant_armor": 200,
    "scroll_charging":      150,
    "scroll_protection_evil": 50,
    "scroll_protection_missiles": 75,
    "scroll_resist_cold":   50,
    "scroll_resist_fire":   50,
    # --- Wands ---
    "wand_magic_missile":  300,
    "wand_firebolt":       400,
    "wand_lightning":      400,
    "wand_cold":           300,
    "wand_poison":         250,
    "wand_death":          500,
    "wand_slowness":       200,
    "wand_amok":           250,
    "wand_teleport":       300,
    "wand_digging":        200,
    "wand_opening":        150,
    "wand_locking":        150,
    "wand_cancellation":   300,
    "wand_disintegrate":   500,
    # --- Rings ---
    "ring_protection":     500,
    "ring_evasion":        500,
    "ring_accuracy":       500,
    "ring_haste":          600,
    "ring_mending":        400,
    "ring_detection":      400,
    "ring_elements":       500,
    "ring_shadows":        500,
    # --- Tools & equipment ---
    "rope":                10,
    "rope_ladder":         10,
    "grappling_hook":      10,
    "pole":                5,
    "chain":               10,
    "lockpicks":           100,
    "crowbar":             10,
    "hammer":              10,
    "chisel":              5,
    "shovel":              10,
    "pickaxe":             10,
    "mattock":             10,
    "pick":                10,
    "drill":               10,
    "saw":                 10,
    "metal_file":          5,
    "nails":               5,
    "iron_stakes":         5,
    "wooden_stakes":       1,
    "iron_tongs":          10,
    "manacles":            10,
    "padlock":             20,
    "pulley":              30,
    "net":                 10,
    "bear_trap":           20,
    "sack":                1,
    "bucket":              5,
    "bellows":             10,
    "mirror":              200,
    "lens":                100,
    "spyglass":            100,
    "hourglass":           300,
    "lantern":             30,
    "torch":               1,
    "candles":             1,
    "tinderbox":           10,
    "lamp_oil":            5,
    "oil_flask":           5,
    "waterskin":           5,
    "sleeping_bag":        10,
    "tent":                50,
    "air_bladder":         5,
    "crampons":            5,
    "fishing_rod":         10,
    "whistle":             5,
    "horn":                10,
    "bell":                20,
    "instrument":          200,
    "chalk":               1,
    "quill_and_ink":       1,
    "blank_book":          300,
    "twine":               5,
    "glue":                1,
    "grease":              1,
    "soap":                1,
    "sponge":              5,
    "perfume":             50,
    "face_paint":          10,
    "pots_and_pans":       10,
    "holy_symbol":         25,
    "holy_water":          25,
    "wolfsbane":           10,
    "garlic":              1,
    "glass_marbles":       5,
    "loaded_dice":         5,
    "fake_jewels":         50,
    # Gems
    "gem_diamond":         500,
    "gem_ruby":            300,
    "gem_emerald":         250,
    "gem_sapphire":        250,
    "gem_amethyst":        150,
    "gem_topaz":           100,
    "gem_opal":            200,
    "gem_garnet":          80,
    "glass_piece_1":       1,
    "glass_piece_2":       1,
    "glass_piece_3":       1,
    "glass_piece_4":       1,
    "glass_piece_5":       1,
    "glass_piece_6":       1,
    "glass_piece_7":       1,
    "glass_piece_8":       1,
    "tar_pot":             10,
    "incense":             10,
    "vial":                1,
    # --- Food ---
    "rations":             5,
    "bread":               2,
    "cheese":              2,
    "apple":               1,
    "dried_meat":          3,
    "mushroom":            1,
    "healing_bandage":     25,
    # --- Gold (not sold in shops, but needed for completeness) ---
    "gold":                1,
}
# fmt: on

_FALLBACK_PRICE = 5


def buy_price(item_id: str) -> int:
    """Return the buy price for *item_id*."""
    return ITEM_PRICES.get(item_id, _FALLBACK_PRICE)


def sell_price(item_id: str) -> int:
    """Return the sell price (half buy price, minimum 1)."""
    return max(1, buy_price(item_id) // 2)


# --- Temple service prices (per depth multiplier) ---
TEMPLE_SERVICE_BASE: dict[str, int] = {
    "heal":         20,
    "remove_curse": 50,
    "bless":        30,
}


def temple_service_price(service_id: str, depth: int) -> int:
    """Return the gold cost of *service_id* on a floor of *depth*.

    Prices scale linearly with depth (depth 1 == base price).
    Unknown services fall back to a sane default so the game never
    crashes on a typo.
    """
    base = TEMPLE_SERVICE_BASE.get(service_id, 30)
    return base * max(1, depth)

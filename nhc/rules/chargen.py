"""Random character generator based on Knave rules (BEB translation).

Generates stats (3d6-take-lowest per ability), HP (1d8), random traits
(physique, face, skin, hair, clothing, virtue, vice, speech, background,
misfortune, alignment), a random name, and starting gold.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, field

from nhc.utils.rng import get_rng, roll_dice


# ── Trait tables (from BEB / Knave) ─────────────────────────────────
# Each table has 20 entries, rolled with 1d20.

PHYSIQUE = [
    "athletic", "brawny", "corpulent", "delicate", "gaunt",
    "giant", "lanky", "muscular", "robust", "scrawny",
    "short", "stout", "slim", "plump", "sculpted",
    "fat", "petite", "tall", "slender", "wiry",
]

FACE = [
    "bloated", "thin", "cadaverous", "chiseled", "delicate",
    "elongated", "stern", "gaunt", "fierce", "broken",
    "wicked", "narrow", "cunning", "round", "sunken",
    "sharp", "soft", "square", "wide", "wild",
]

SKIN = [
    "battle_scar", "birthmark", "burned", "dark", "painted",
    "greasy", "sallow", "flawless", "pierced", "pockmarked",
    "sweaty", "tattooed", "radiant", "rough", "pale",
    "sunburned", "tanned", "war_paint", "wrinkled", "whipped",
]

HAIR = [
    "bald", "braided", "bristly", "half_shaved", "curly",
    "disheveled", "dreadlocks", "filthy", "frizzy", "greasy",
    "limp", "long", "luxurious", "mohawk", "oily",
    "ponytail", "silky", "topknot", "wavy", "feathery",
]

CLOTHING = [
    "antique", "bloody", "ceremonial", "decorated", "eccentric",
    "elegant", "distinguished", "provocative", "flashy", "stained",
    "foreign", "worn", "oversized", "uniform", "large",
    "patched", "perfumed", "rancid", "tattered", "small",
]

VIRTUE = [
    "ambitious", "cautious", "brave", "courteous", "curious",
    "disciplined", "focused", "generous", "gregarious", "honest",
    "honorable", "humble", "idealistic", "just", "loyal",
    "compassionate", "proper", "serene", "stoic", "tolerant",
]

VICE = [
    "aggressive", "arrogant", "bitter", "cowardly", "cruel",
    "deceitful", "frivolous", "gluttonous", "greedy", "irascible",
    "lazy", "nervous", "prejudiced", "reckless", "rude",
    "suspicious", "vain", "vengeful", "wasteful", "whiny",
]

SPEECH = [
    "gruff", "deep", "halting", "cryptic", "drawling",
    "singsong", "flowery", "formal", "grave", "hoarse",
    "mumbling", "precise", "quaint", "incoherent", "rapid",
    "dialectal", "calm", "booming", "stuttering", "whispering",
]

BACKGROUND = [
    "alchemist", "beggar", "butcher", "burglar", "charlatan",
    "cleric", "cook", "cultist", "gambler", "herbalist",
    "wizard", "sailor", "mercenary", "merchant", "outlaw",
    "performer", "pickpocket", "smuggler", "student", "tracker",
]

MISFORTUNE = [
    "abandoned", "addicted", "blackmailed", "condemned", "cursed",
    "swindled", "demoted", "discredited", "dispossessed", "exiled",
    "sentenced", "obsessed", "kidnapped", "mutilated", "destitute",
    "hunted", "expelled", "replaced", "robbed", "suspected",
]

ALIGNMENT = ["lawful", "neutral", "chaotic"]

# Weighted alignment roll: 1-5 lawful, 6-15 neutral, 16-20 chaotic
_ALIGNMENT_THRESHOLDS = [(5, "lawful"), (15, "neutral"), (20, "chaotic")]

# ── Name tables ─────────────────────────────────────────────────────
# Mix of medieval/fantasy names suitable for a Catalan-flavored setting.

NAMES_MALE = [
    "Arnau", "Bernat", "Carles", "Dídac", "Esteve",
    "Ferran", "Guillem", "Hug", "Jordi", "Llorenç",
    "Marc", "Narcís", "Oriol", "Pere", "Quim",
    "Ramon", "Salvador", "Toni", "Ulf", "Valentí",
]

NAMES_FEMALE = [
    "Aina", "Blanca", "Carme", "Dolors", "Elsa",
    "Fiona", "Gemma", "Helena", "Irene", "Joana",
    "Laia", "Mercè", "Núria", "Olga", "Pilar",
    "Queralt", "Rosa", "Sílvia", "Teresa", "Violeta",
]

SURNAMES = [
    "Boscater", "Ferrer", "Llopis", "Puig", "Serra",
    "Valls", "Agramunt", "Cardona", "Montcada", "Torrelles",
    "Bellpuig", "Castellar", "Olesa", "Ribes", "Soler",
    "Figueres", "Manresa", "Peralada", "Rosselló", "Vilafranca",
]


@dataclass
class CharacterSheet:
    """A randomly generated character."""

    name: str = ""
    # Ability bonuses (Knave: defense = bonus + 10)
    strength: int = 0
    dexterity: int = 0
    constitution: int = 0
    intelligence: int = 0
    wisdom: int = 0
    charisma: int = 0
    hp: int = 1
    gold: int = 0
    # Traits
    physique: str = ""
    face: str = ""
    skin: str = ""
    hair: str = ""
    clothing: str = ""
    virtue: str = ""
    vice: str = ""
    speech: str = ""
    background: str = ""
    misfortune: str = ""
    alignment: str = ""
    # Starting equipment (item registry IDs)
    starting_items: list[str] = field(default_factory=list)


def _roll_ability(rng) -> int:
    """Roll 3d6, take the lowest die as the ability bonus."""
    dice = [rng.randint(1, 6) for _ in range(3)]
    return min(dice)


def _pick(table: list[str], rng) -> str:
    """Pick a random entry from a 20-item trait table."""
    return table[rng.randint(0, len(table) - 1)]


def _roll_alignment(rng) -> str:
    """Roll 1d20 for alignment: 1-5 lawful, 6-15 neutral, 16-20 chaotic."""
    roll = rng.randint(1, 20)
    for threshold, align in _ALIGNMENT_THRESHOLDS:
        if roll <= threshold:
            return align
    return "neutral"


# ── Starting equipment tables (Knave rules) ─────────────────────────

# Armor: roll 1d20
ARMOR_TABLE = [
    (3, None),              # 1-3: no armor
    (14, "gambeson"),       # 4-14: gambeson (defense 12)
    (19, "brigantine"),     # 15-19: brigantine (defense 13)
    (20, "chain_mail"),     # 20: chain mail (defense 14)
]

# Helm/Shield: roll 1d20
HELM_SHIELD_TABLE = [
    (13, None),             # 1-13: nothing
    (16, "helmet"),         # 14-16: helmet (+1 defense)
    (19, "shield"),         # 17-19: shield (+1 defense)
    (20, "helmet+shield"),  # 20: both
]

# Weapon: player gets one weapon (d6 tier)
WEAPON_TABLE = ["dagger", "club", "short_sword", "sword", "spear", "axe", "mace"]

# Loot table (roll 2x from this — matches Knave "Saqueig" table)
LOOT_TABLE = [
    "rope", "pulley", "candles", "chain", "chalk",
    "crowbar", "tinderbox", "grappling_hook", "hammer", "waterskin",
    "lantern", "lamp_oil", "padlock", "manacles", "mirror",
    "pole", "sack", "tent", "iron_stakes", "torch",
]

# General equipment 1 table (roll 1x)
GENERAL_EQUIPMENT_1 = [
    "air_bladder", "bear_trap", "shovel", "bellows", "grease",
    "saw", "bucket", "glass_marbles", "chisel", "drill",
    "fishing_rod", "glue", "pick", "hourglass",
    "net", "iron_tongs", "lockpicks", "metal_file", "nails",
]

# General equipment 2 table (roll 1x)
GENERAL_EQUIPMENT_2 = [
    "incense", "sponge", "lens", "perfume", "horn",
    "vial", "soap", "spyglass", "tar_pot", "twine",
    "fake_jewels", "blank_book", "loaded_dice",
    "pots_and_pans", "face_paint", "whistle", "instrument",
    "quill_and_ink", "bell",
]

# Starting consumables: always rations + 1 healing potion + 1 random scroll
STARTING_SCROLLS = [
    "scroll_light", "scroll_cure_wounds", "scroll_bless",
    "scroll_detect_magic", "scroll_find_traps", "scroll_sleep",
    "scroll_remove_fear", "scroll_shield",
]


def _roll_table(table: list[tuple[int, int | None]], rng) -> str | None:
    """Roll 1d20 against a threshold table."""
    roll = rng.randint(1, 20)
    for threshold, item in table:
        if roll <= threshold:
            return item
    return None


def _roll_starting_equipment(rng) -> list[str]:
    """Roll starting equipment per Knave rules.

    - 1 weapon (random)
    - Armor roll (1d20)
    - Helm/shield roll (1d20)
    - 2 rolls on loot table
    - 2 days rations
    - 1 healing potion
    - 1 random starting scroll
    """
    items: list[str] = []

    # One weapon
    items.append(rng.choice(WEAPON_TABLE))

    # Armor roll
    armor = _roll_table(ARMOR_TABLE, rng)
    if armor:
        items.append(armor)

    # Helm/shield roll
    helm_shield = _roll_table(HELM_SHIELD_TABLE, rng)
    if helm_shield == "helmet+shield":
        items.append("helmet")
        items.append("shield")
    elif helm_shield:
        items.append(helm_shield)

    # 2 rolls on loot table (Knave: "Tira dos cops sobre Saqueig")
    loot_picks = rng.sample(LOOT_TABLE, min(2, len(LOOT_TABLE)))
    items.extend(loot_picks)

    # 1 roll on general equipment 1
    items.append(rng.choice(GENERAL_EQUIPMENT_1))

    # 1 roll on general equipment 2
    items.append(rng.choice(GENERAL_EQUIPMENT_2))

    # Always: rations + healing potion + random scroll
    items.append("rations")
    items.append("healing_potion")
    items.append(rng.choice(STARTING_SCROLLS))

    return items


def generate_character(seed: int | None = None) -> CharacterSheet:
    """Generate a random Knave character.

    Uses the game RNG if no seed is provided, otherwise creates a
    dedicated RNG for reproducibility.
    """
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = get_rng()

    # Ability scores: 3d6, take lowest
    strength = _roll_ability(rng)
    dexterity = _roll_ability(rng)
    constitution = _roll_ability(rng)
    intelligence = _roll_ability(rng)
    wisdom = _roll_ability(rng)
    charisma = _roll_ability(rng)

    # HP: 1d8
    hp = rng.randint(1, 8)

    # Starting gold: 3d6 × 20 copper → convert to gold (÷10)
    copper = sum(rng.randint(1, 6) for _ in range(3)) * 20
    gold = copper // 10

    # Random name
    if rng.random() < 0.5:
        first = _pick(NAMES_MALE, rng)
    else:
        first = _pick(NAMES_FEMALE, rng)
    surname = _pick(SURNAMES, rng)
    name = f"{first} {surname}"

    # Starting equipment
    starting_items = _roll_starting_equipment(rng)

    return CharacterSheet(
        name=name,
        strength=strength,
        dexterity=dexterity,
        constitution=constitution,
        intelligence=intelligence,
        wisdom=wisdom,
        charisma=charisma,
        hp=hp,
        gold=gold,
        physique=_pick(PHYSIQUE, rng),
        face=_pick(FACE, rng),
        skin=_pick(SKIN, rng),
        hair=_pick(HAIR, rng),
        clothing=_pick(CLOTHING, rng),
        virtue=_pick(VIRTUE, rng),
        vice=_pick(VICE, rng),
        speech=_pick(SPEECH, rng),
        background=_pick(BACKGROUND, rng),
        misfortune=_pick(MISFORTUNE, rng),
        alignment=_roll_alignment(rng),
        starting_items=starting_items,
    )

"""Random character generator based on Knave rules (BEB translation).

Generates stats (3d6-take-lowest per ability), HP (1d8), random traits
(physique, face, skin, hair, clothing, virtue, vice, speech, background,
misfortune, alignment), a random name, and starting gold.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from nhc.i18n import current_lang
from nhc.tables.registry import TableRegistry
from nhc.utils.rng import get_rng, roll_dice


# Language used to load the trait registry for chargen. Traits are
# shared_structure, so entry_ids are identical across locales; any
# locale works to surface the entry_id we store on the sheet.
_TRAIT_LANG = "en"

_TRAIT_TABLE_BY_AXIS = {
    "physique": "trait.physique",
    "face": "trait.face",
    "skin": "trait.skin",
    "hair": "trait.hair",
    "clothing": "trait.clothing",
    "virtue": "trait.virtue",
    "vice": "trait.vice",
    "speech": "trait.speech",
    "background": "trait.background",
    "misfortune": "trait.misfortune",
    "alignment": "trait.alignment",
}


def _roll_trait(axis: str, rng: random.Random) -> str:
    """Roll a trait axis via the TableRegistry, returning the entry id."""
    registry = TableRegistry.get_or_load(_TRAIT_LANG)
    table_id = _TRAIT_TABLE_BY_AXIS[axis]
    return registry.roll(table_id, rng=rng, context={}).entry_id


def trait_text(axis: str, entry_id: str, lang: str | None = None) -> str:
    """Localized text for a trait entry_id.

    Defaults to the current i18n language. Raises KeyError for
    unknown axes or unknown entry ids.
    """
    table_id = _TRAIT_TABLE_BY_AXIS[axis]
    registry = TableRegistry.get_or_load(lang or current_lang())
    return registry.render(table_id, entry_id=entry_id, context={}).text


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


# ── Starting equipment tables (Knave rules) ─────────────────────────

# Armor: roll 1d20
ARMOR_TABLE = [
    (3, None),              # 1-3: no armor
    (14, "gambeson"),       # 4-14: gambeson (defense 12)
    (19, "brigandine"),     # 15-19: brigandine (defense 13)
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
    items.append("potion_healing")
    items.append(rng.choice(STARTING_SCROLLS))

    return items


def generate_character(
    seed: int | None = None,
    *,
    double_gold: bool = False,
) -> CharacterSheet:
    """Generate a random Knave character.

    Uses the game RNG if no seed is provided, otherwise creates a
    dedicated RNG for reproducibility. When *double_gold* is True,
    roll 6d6 instead of 3d6 for starting gold (easy/medium
    difficulty).
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

    # HP: max hit die at level 1 (Knave survivability rule)
    hp = 8

    # Starting gold: 3d6 × 20 copper → gold (÷10); double = 6d6
    dice = 6 if double_gold else 3
    copper = sum(rng.randint(1, 6) for _ in range(dice)) * 20
    gold = copper // 10

    # Random name
    if rng.random() < 0.5:
        first = rng.choice(NAMES_MALE)
    else:
        first = rng.choice(NAMES_FEMALE)
    surname = rng.choice(SURNAMES)
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
        physique=_roll_trait("physique", rng),
        face=_roll_trait("face", rng),
        skin=_roll_trait("skin", rng),
        hair=_roll_trait("hair", rng),
        clothing=_roll_trait("clothing", rng),
        virtue=_roll_trait("virtue", rng),
        vice=_roll_trait("vice", rng),
        speech=_roll_trait("speech", rng),
        background=_roll_trait("background", rng),
        misfortune=_roll_trait("misfortune", rng),
        alignment=_roll_trait("alignment", rng),
        starting_items=starting_items,
    )

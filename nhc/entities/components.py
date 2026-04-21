"""Reusable ECS components for entities."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    x: int = 0
    y: int = 0
    level_id: str = ""


@dataclass
class Renderable:
    glyph: str = "?"
    color: str = "white"
    render_order: int = 0


@dataclass
class Stats:
    """Knave ability scores (bonus values; defense = bonus + 10)."""
    strength: int = 0
    dexterity: int = 0
    constitution: int = 0
    intelligence: int = 0
    wisdom: int = 0
    charisma: int = 0


@dataclass
class Health:
    current: int = 1
    maximum: int = 1


@dataclass
class Inventory:
    slots: list[int] = field(default_factory=list)  # EntityIds
    max_slots: int = 11  # CON defense (CON bonus + 10)


@dataclass
class AI:
    behavior: str = "idle"
    morale: int = 7
    faction: str = "neutral"
    # Morale state machine: unaware → engaged | hesitant → fleeing.
    # Tracked at runtime; not part of any creature factory recipe.
    state: str = "unaware"
    # One-shot flag: True after the creature has rolled its
    # half-HP morale check, so it does not re-roll every tick.
    morale_checked_on_hp: bool = False


@dataclass
class Description:
    name: str = ""
    short: str = ""
    long: str = ""
    gender: str = ""  # "m" or "f" for grammatical gender (articles)
    plural: str = ""  # plural form of name, used for stack labels


@dataclass
class LootTable:
    entries: list[tuple] = field(default_factory=list)
    # Each entry: (item_id, probability) or (item_id, probability, dice)


@dataclass
class RegistryId:
    """Tracks the original entity registry key."""
    item_id: str = ""


@dataclass
class SubHexStableId:
    """Stable identity for entities spawned by the sub-hex populator.

    Populator stamps ``f"{registry_id}_{x}_{y}"`` on every creature,
    NPC, item, and feature it spawns so the C3 mutation replay path
    can recognise "this is the same placement as last visit" when
    the player re-enters a previously-evicted sub-hex site.
    """

    stable_id: str = ""


@dataclass
class ShopInventory:
    """Items for sale at this merchant."""
    stock: list[str] = field(default_factory=list)


@dataclass
class TempleServices:
    """Spell-like services a priest can perform on the spot.

    Service IDs are looked up in the temple action dispatcher; prices
    scale with floor depth via :func:`nhc.rules.prices.temple_service_price`.
    """
    services: list[str] = field(default_factory=list)


@dataclass
class RumorVendor:
    """Marker component for NPCs who dispense overland rumors.

    Present on innkeepers in settlement inn rooms; :class:`BumpAction`
    dispatches an :class:`InnkeeperInteractAction` when the player
    bumps a RumorVendor. The action side consults the active
    :class:`HexWorld` (not stored here; supplied by the caller)
    because rumors are overland-scope state, not per-entity.
    """
    pass


@dataclass
class Disguise:
    appears_as: str = ""
    reveal_on: str = "interact"


@dataclass
class Player:
    """Tag component identifying the player entity."""
    xp: int = 0
    level: int = 1
    xp_to_next: int = 1000
    gold: int = 0


@dataclass
class Errand:
    """Per-NPC state for the `errand` behavior.

    Town villagers path toward ``(target_x, target_y)``; on arrival
    they idle for a few turns (simulating a visit) and then pick a
    new destination. When both target fields are ``None`` the
    behavior picks a fresh walkable street tile.
    """
    target_x: int | None = None
    target_y: int | None = None
    idle_turns_remaining: int = 0


@dataclass
class BlocksMovement:
    """Tag component for entities that block tile movement."""


@dataclass
class Weapon:
    damage: str = "1d6"
    type: str = "melee"
    slots: int = 1
    magic_bonus: int = 0  # +N to attack and damage rolls


@dataclass
class DiggingTool:
    """Tool for excavating walls."""
    bonus: int = 0  # added to STR check for digging
    can_dig_floor: bool = False  # only shovels can dig down


@dataclass
class Consumable:
    effect: str = ""
    dice: str = ""
    slots: int = 1


@dataclass
class Trap:
    damage: str = "1d6"
    dc: int = 12
    hidden: bool = True
    triggered: bool = False
    effect: str = ""  # "", "poison", "paralysis", "alarm", "teleport",
                      # "summoning", "gripping", "fire", "arrow",
                      # "darts", "falling_stone", "spores"
    reactivatable: bool = False  # True for lair traps (re-hide after 40 turns)
    triggered_at_turn: int | None = None  # turn when last triggered


@dataclass
class Armor:
    """Armor piece with slot and defense value."""
    slot: str = "body"  # "body", "shield", "helmet"
    defense: int = 0    # AC bonus or base defense
    slots: int = 1      # inventory slots consumed
    magic_bonus: int = 0  # +N to AC


@dataclass
class Ring:
    """Passive magical ring — effect active while equipped."""
    effect: str = ""  # "mending", "haste", "detection", etc.


@dataclass
class Throwable:
    """Tag: item can be thrown at a target."""
    pass


@dataclass
class Wand:
    """Rechargeable magical device with charges."""
    effect: str = ""
    charges: int = 0
    max_charges: int = 0
    recharge_timer: int = 20  # turns until next charge gained


@dataclass
class Equipment:
    """Currently equipped items."""
    weapon: int | None = None
    armor: int | None = None
    shield: int | None = None
    helmet: int | None = None
    ring_left: int | None = None
    ring_right: int | None = None


@dataclass
class StatusEffect:
    """Temporary status affecting an entity's actions."""
    paralyzed: int = 0      # turns remaining (Hold Person / PetrifyingGaze)
    sleeping: int = 0       # turns remaining (Sleep — broken by damage)
    hasted: int = 0         # turns remaining (double attacks)
    blessed: int = 0        # turns remaining (+1 attack/damage)
    invisible: int = 0      # turns remaining (breaks on attack)
    mirror_images: int = 0  # illusion copies remaining (each absorbs 1 hit)
    protected: int = 0      # turns remaining (+1 saves, -1 enemy attacks)
    webbed: int = 0         # turns remaining (cannot move)
    charmed: int = 0        # turns remaining (fights for caster)
    shielded: int = 0       # turns remaining (+2 AC bonus)
    resist_cold: int = 0    # turns remaining (halve cold damage)
    resist_fire: int = 0    # turns remaining (halve fire damage)
    levitating: int = 0     # turns remaining (ignore traps, float over terrain)
    flying: int = 0         # turns remaining (move freely, ignore terrain)
    prot_missiles: int = 0  # turns remaining (immune to ranged attacks)
    silenced: int = 0       # turns remaining (cannot use scrolls in radius)
    infravision: int = 0    # turns remaining (see in dark, extended FOV)
    water_breathing: int = 0  # turns remaining (survive water tiles)
    confused: int = 0       # turns remaining (random movement)
    blinded: int = 0        # turns remaining (cannot see, reduced FOV)


@dataclass
class Undead:
    """Tag: undead creature (immune to sleep/charm, vulnerable to turning)."""


@dataclass
class Poison:
    """Tag: entity is currently poisoned."""
    damage_per_turn: int = 1
    turns_remaining: int = 3


@dataclass
class BloodDrain:
    """Attacker drains blood: deals bonus drain damage and heals self for that amount."""
    drain_per_hit: int = 2


@dataclass
class PetrifyingTouch:
    """Tag: on a successful melee hit, target must save DEX 12 or be paralyzed."""


@dataclass
class FrostBreath:
    """Attacker exhales cold on a hit, dealing bonus cold damage."""
    dice: str = "1d6"


@dataclass
class DisenchantTouch:
    """Tag: on a hit, destroys one consumable item in the target's inventory."""


@dataclass
class Regeneration:
    """Creature heals hp_per_turn at end of each turn (unless fire-damaged)."""
    hp_per_turn: int = 3
    fire_damaged: bool = False  # set True when hit by fire; clears on tick


@dataclass
class MummyRot:
    """Tag: on a hit, target's max HP drops by 1 per 2 turns until cured."""


@dataclass
class FearAura:
    """Creatures within radius must pass a STR save or flee (skip turn)."""
    radius: int = 3
    save_dc: int = 12


@dataclass
class RequiresMagicWeapon:
    """Tag: non-enchanted weapons deal no damage to this creature."""


@dataclass
class DeathWail:
    """Banshee: each turn a humanoid is in range, must save CON or die."""
    radius: int = 5
    save_dc: int = 15


@dataclass
class CharmSong:
    """Harpy: humanoids in radius must move toward the harpy each turn."""
    radius: int = 6
    save_dc: int = 12


@dataclass
class Enchanted:
    """Tag: weapon is magical and can bypass RequiresMagicWeapon defense."""


@dataclass
class Detected:
    """Entity was revealed by a detection spell (fading glow)."""
    turn_detected: int = 0
    duration: int = 20
    glow_color: str = "#00CCFF"


@dataclass
class BuriedMarker:
    """Tag: glowing indicator placed by search over a buried-item tile."""
    expires_at_turn: int = 0


@dataclass
class Cursed:
    """Tag: creature is under a mummy's rot curse."""
    ticks_until_drain: int = 2  # decrements each turn; drains 1 max HP at 0


@dataclass
class Gem:
    """Valuable gemstone with a gold value."""
    value: int = 100


@dataclass
class Henchman:
    """Recruitable adventurer / active party member."""
    owner: int | None = None    # player entity ID when hired
    level: int = 1
    xp: int = 0
    xp_to_next: int = 1000
    hired: bool = False
    called_for_help: bool = False  # prevents repeated cry messages
    gold: int = 0               # personal gold purse


@dataclass
class Hunger:
    """Tracks player satiation.  Decrements by 1 each turn.

    States (derived from current):
      Satiated: current > 1000
      Normal:   300 < current ≤ 1000
      Hungry:   100 < current ≤ 300
      Starving: current ≤ 100
    """
    current: int = 900
    maximum: int = 1200
    prev_state: str = "normal"
    str_penalty: int = 0
    dex_penalty: int = 0

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


@dataclass
class Description:
    name: str = ""
    short: str = ""
    long: str = ""


@dataclass
class LootTable:
    entries: list[tuple] = field(default_factory=list)
    # Each entry: (item_id, probability) or (item_id, probability, dice)


@dataclass
class Disguise:
    appears_as: str = ""
    reveal_on: str = "interact"


@dataclass
class Player:
    """Tag component identifying the player entity."""


@dataclass
class BlocksMovement:
    """Tag component for entities that block tile movement."""


@dataclass
class Weapon:
    damage: str = "1d6"
    type: str = "melee"
    slots: int = 1


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


@dataclass
class Equipment:
    """Currently equipped items."""
    weapon: int | None = None  # EntityId of equipped weapon

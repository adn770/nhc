"""Combat resolution: attack rolls, damage, morale (Knave rules)."""

from __future__ import annotations

import random

from nhc.entities.components import Health, Stats
from nhc.utils.rng import d20, roll_dice, roll_dice_max


def resolve_melee_attack(
    attacker_stats: Stats,
    target_stats: Stats,
    weapon_damage: str = "1d6",
    rng: random.Random | None = None,
) -> tuple[bool, int]:
    """Resolve a melee attack.

    Knave rules:
        Attack roll: d20 + STR bonus >= target armor defense (10 + DEX bonus)
        Damage: weapon die + STR bonus
        Natural 20: maximum damage

    Returns:
        (hit: bool, damage: int). Damage is 0 on miss.
    """
    roll = d20(rng)

    # Natural 20 always hits with max damage
    if roll == 20:
        damage = roll_dice_max(weapon_damage) + attacker_stats.strength
        return True, max(1, damage)

    # Natural 1 always misses
    if roll == 1:
        return False, 0

    attack_total = roll + attacker_stats.strength
    armor_defense = 10 + target_stats.dexterity

    if attack_total >= armor_defense:
        damage = roll_dice(weapon_damage, rng) + attacker_stats.strength
        return True, max(1, damage)

    return False, 0


def apply_damage(health: Health, damage: int) -> int:
    """Apply damage to health, returning actual damage dealt."""
    actual = min(damage, health.current)
    health.current -= actual
    return actual


def heal(health: Health, amount: int) -> int:
    """Heal up to max HP, returning actual amount healed."""
    actual = min(amount, health.maximum - health.current)
    health.current += actual
    return actual


def is_dead(health: Health) -> bool:
    return health.current <= 0

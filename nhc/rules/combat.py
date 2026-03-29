"""Combat resolution: attack rolls, damage, morale (Knave rules)."""

from __future__ import annotations

import logging
import random

from nhc.entities.components import Health, Stats
from nhc.utils.rng import d20, roll_dice, roll_dice_max

logger = logging.getLogger(__name__)


def resolve_melee_attack(
    attacker_stats: Stats,
    target_stats: Stats,
    weapon_damage: str = "1d6",
    rng: random.Random | None = None,
    attack_bonus: int = 0,
    damage_bonus: int = 0,
    armor_bonus: int = 0,
) -> tuple[bool, int]:
    """Resolve a melee attack.

    Knave rules:
        Attack roll: d20 + STR bonus + attack_bonus >= target AC
        Target AC: 10 + DEX bonus + armor_bonus
        Damage: weapon die + STR bonus + damage_bonus
        Natural 20: maximum damage

    attack_bonus/damage_bonus come from magic weapons (+N).
    armor_bonus comes from magic armor on the target.

    Returns:
        (hit: bool, damage: int). Damage is 0 on miss.
    """
    roll = d20(rng)

    # Natural 20 always hits with max damage
    if roll == 20:
        damage = (roll_dice_max(weapon_damage)
                  + attacker_stats.strength + damage_bonus)
        logger.debug("Nat 20! max dmg=%d", max(1, damage))
        return True, max(1, damage)

    # Natural 1 always misses
    if roll == 1:
        logger.debug("Nat 1 — auto miss")
        return False, 0

    attack_total = roll + attacker_stats.strength + attack_bonus
    armor_defense = 10 + target_stats.dexterity + armor_bonus

    if attack_total >= armor_defense:
        damage = (roll_dice(weapon_damage, rng)
                  + attacker_stats.strength + damage_bonus)
        logger.debug(
            "Hit: roll=%d+STR%d+mag%d=%d vs AC%d, dmg=%d",
            roll, attacker_stats.strength, attack_bonus,
            attack_total, armor_defense, max(1, damage),
        )
        return True, max(1, damage)

    logger.debug(
        "Miss: roll=%d+STR%d+mag%d=%d vs AC%d",
        roll, attacker_stats.strength, attack_bonus,
        attack_total, armor_defense,
    )
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

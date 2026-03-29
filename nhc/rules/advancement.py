"""XP, leveling, HP advancement (Knave rules).

Knave advancement:
- Every 1000 XP = 1 level (linear)
- HP on level up: roll new_level × d8; use if > old max, else old max + 1
- 3 different abilities raised by 1 (lowest first), capped at 10
- Max level 10
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from nhc.entities.components import Health, Player, Stats
from nhc.i18n import t
from nhc.utils.rng import roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World

logger = logging.getLogger(__name__)

# XP awarded per creature based on their max HP
XP_PER_HP = 5

# Knave: 1000 XP per level
XP_PER_LEVEL = 1000

# Max level and ability bonus caps
MAX_LEVEL = 10
MAX_ABILITY_BONUS = 10

# Number of abilities raised per level up
ABILITIES_PER_LEVEL = 3


def xp_for_level(level: int) -> int:
    """Cumulative XP needed to reach a given level.

    Level 1 = 0, Level 2 = 1000, Level 3 = 2000, etc.
    """
    return max(0, (level - 1) * XP_PER_LEVEL)


def award_xp(world: "World", player_id: int, target_id: int) -> int:
    """Award XP for killing a creature. Returns XP gained.

    NOTE: This looks up the target's Health component, which must still
    exist.  For events fired *after* entity destruction, use
    ``award_xp_direct`` with the pre-captured max_hp instead.
    """
    target_health = world.get_component(target_id, "Health")
    max_hp = target_health.maximum if target_health else 0
    return award_xp_direct(world, player_id, max_hp)


def award_xp_direct(world: "World", player_id: int, max_hp: int) -> int:
    """Award XP from a pre-captured max_hp value. Returns XP gained."""
    player = world.get_component(player_id, "Player")
    if not player or max_hp <= 0:
        return 0

    xp = max_hp * XP_PER_HP
    player.xp += xp
    logger.info(
        "XP awarded: %d (creature max_hp=%d), total=%d",
        xp, max_hp, player.xp,
    )
    return xp


def check_level_up(world: "World", player_id: int) -> list[str]:
    """Check if player has enough XP to level up.

    Returns list of messages describing level-up effects.
    Knave rules: roll new_level*d8 for HP (min +1), raise 3 abilities.
    """
    player = world.get_component(player_id, "Player")
    if not player:
        return []

    messages: list[str] = []

    while player.xp >= player.xp_to_next and player.level < MAX_LEVEL:
        player.level += 1
        player.xp_to_next = xp_for_level(player.level + 1)

        # ── HP: Knave reroll ──
        # Roll new_level × d8. If > old max, use it; else old max + 1.
        hp_gain = 0
        health = world.get_component(player_id, "Health")
        if health:
            rolled = roll_dice(f"{player.level}d8")
            if rolled > health.maximum:
                hp_gain = rolled - health.maximum
            else:
                hp_gain = 1
            health.maximum += hp_gain
            health.current += hp_gain

        # ── Abilities: raise 3 lowest (Knave) ──
        stats = world.get_component(player_id, "Stats")
        raised_names: list[str] = []
        if stats:
            abilities = _pick_lowest_abilities(stats, ABILITIES_PER_LEVEL)
            for ability in abilities:
                old_val = getattr(stats, ability)
                setattr(stats, ability, old_val + 1)
                raised_names.append(t(f"stats.{ability}"))

            # Update inventory capacity (Knave: slots = CON bonus + 10)
            inv = world.get_component(player_id, "Inventory")
            if inv:
                inv.max_slots = stats.constitution + 10

        if raised_names:
            abilities_str = ", ".join(raised_names)
            messages.append(
                t("levelup.with_abilities", level=player.level,
                  hp=hp_gain, abilities=abilities_str),
            )
        else:
            messages.append(
                t("levelup.no_ability", level=player.level, hp=hp_gain),
            )

        logger.info(
            "Level up! Now level %d, +%d HP, abilities: %s",
            player.level, hp_gain,
            ", ".join(raised_names) if raised_names else "none",
        )

    return messages


def _pick_lowest_abilities(stats: Stats, count: int = 3) -> list[str]:
    """Pick the N lowest ability scores that aren't capped.

    Ties broken by definition order (STR, DEX, CON, INT, WIS, CHA).
    """
    abilities = [
        ("strength", stats.strength),
        ("dexterity", stats.dexterity),
        ("constitution", stats.constitution),
        ("intelligence", stats.intelligence),
        ("wisdom", stats.wisdom),
        ("charisma", stats.charisma),
    ]
    # Filter out capped abilities
    eligible = [(name, val) for name, val in abilities
                if val < MAX_ABILITY_BONUS]
    # Sort by value (stable sort preserves definition order for ties)
    eligible.sort(key=lambda x: x[1])
    return [name for name, _ in eligible[:count]]

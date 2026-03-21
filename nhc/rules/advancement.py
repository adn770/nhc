"""XP, leveling, HP advancement (Knave rules)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nhc.entities.components import Health, Player, Stats
from nhc.i18n import t
from nhc.utils.rng import roll_dice

if TYPE_CHECKING:
    from nhc.core.ecs import World

# XP awarded per creature based on their max HP
# Simple formula: XP = max_hp * 5
XP_PER_HP = 5

# XP required per level (cumulative thresholds)
# Level 2: 20, Level 3: 60, Level 4: 120, etc.
def xp_for_level(level: int) -> int:
    """XP needed to reach the given level from 0."""
    return level * (level - 1) * 10


def award_xp(world: "World", player_id: int, target_id: int) -> int:
    """Award XP for killing a creature. Returns XP gained."""
    player = world.get_component(player_id, "Player")
    if not player:
        return 0

    target_health = world.get_component(target_id, "Health")
    if not target_health:
        return 0

    xp = target_health.maximum * XP_PER_HP
    player.xp += xp
    return xp


def check_level_up(world: "World", player_id: int) -> list[str]:
    """Check if player has enough XP to level up.

    Returns list of messages describing level-up effects.
    Knave rules: +1d8 HP per level, raise one ability by 1.
    """
    player = world.get_component(player_id, "Player")
    if not player:
        return []

    messages: list[str] = []

    while player.xp >= player.xp_to_next:
        player.level += 1
        player.xp_to_next = xp_for_level(player.level + 1)

        # Gain HP (Knave: 1d8 per level)
        hp_gain = roll_dice("1d8")
        health = world.get_component(player_id, "Health")
        if health:
            health.maximum += hp_gain
            health.current += hp_gain

        # Auto-raise a random ability by 1
        stats = world.get_component(player_id, "Stats")
        if stats:
            ability = _pick_lowest_ability(stats)
            old_val = getattr(stats, ability)
            setattr(stats, ability, old_val + 1)
            messages.append(
                t("levelup.with_ability", level=player.level,
                  hp=hp_gain, ability=ability.upper()),
            )
        else:
            messages.append(
                t("levelup.no_ability", level=player.level,
                  hp=hp_gain),
            )

    return messages


def _pick_lowest_ability(stats: Stats) -> str:
    """Pick the lowest ability score (ties broken by priority order)."""
    abilities = [
        ("strength", stats.strength),
        ("dexterity", stats.dexterity),
        ("constitution", stats.constitution),
        ("intelligence", stats.intelligence),
        ("wisdom", stats.wisdom),
        ("charisma", stats.charisma),
    ]
    return min(abilities, key=lambda x: x[1])[0]

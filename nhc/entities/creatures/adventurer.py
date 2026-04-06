"""Adventurer — recruitable henchman NPC with chargen stats."""

from __future__ import annotations

from nhc.entities.components import (
    AI, BlocksMovement, Description, Equipment, Health, Henchman,
    Inventory, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry
from nhc.rules.advancement import (
    ABILITIES_PER_LEVEL, MAX_ABILITY_BONUS, XP_PER_LEVEL,
    _pick_lowest_abilities,
)
from nhc.rules.chargen import generate_character
from nhc.utils.rng import roll_dice


def create_adventurer_at_level(
    level: int,
    seed: int | None = None,
) -> dict:
    """Create an adventurer with chargen stats scaled to *level*.

    Applies Knave level-up rules (level - 1) times to simulate
    a character that has advanced to the given level.
    """
    char = generate_character(seed)

    stats = Stats(
        strength=char.strength,
        dexterity=char.dexterity,
        constitution=char.constitution,
        intelligence=char.intelligence,
        wisdom=char.wisdom,
        charisma=char.charisma,
    )
    hp = char.hp  # 8 at level 1

    # Apply level-up rules (level - 1) times
    for lv in range(2, level + 1):
        # HP: roll lv × d8; use if > old max, else +1
        rolled = roll_dice(f"{lv}d8")
        if rolled > hp:
            hp = rolled
        else:
            hp += 1

        # Raise 3 lowest abilities
        abilities = _pick_lowest_abilities(stats, ABILITIES_PER_LEVEL)
        for ability in abilities:
            old_val = getattr(stats, ability)
            if old_val < MAX_ABILITY_BONUS:
                setattr(stats, ability, old_val + 1)

    return {
        "Stats": stats,
        "Health": Health(current=hp, maximum=hp),
        "Inventory": Inventory(max_slots=stats.constitution + 10),
        "Equipment": Equipment(),
        "Renderable": Renderable(
            glyph="@", color="cyan", render_order=2,
        ),
        "AI": AI(behavior="henchman", morale=8, faction="human"),
        "Henchman": Henchman(
            level=level,
            xp=(level - 1) * XP_PER_LEVEL,
            xp_to_next=level * XP_PER_LEVEL,
        ),
        "BlocksMovement": BlocksMovement(),
        "Description": Description(
            name=char.name,
            short=char.name,
        ),
    }


@EntityRegistry.register_creature("adventurer")
def create_adventurer() -> dict:
    """Default factory — level 1 adventurer."""
    return create_adventurer_at_level(1)

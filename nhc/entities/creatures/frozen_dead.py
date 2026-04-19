"""Frozen Dead — icebound undead variant. (BEB-style: FrozenDead)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Undead,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("frozen_dead")
def create_frozen_dead() -> dict:
    return {
        "Renderable": Renderable(
            glyph="z", color="bright_cyan", render_order=2,
        ),
        "Description": creature_desc("frozen_dead"),
        "Stats": Stats(strength=2, dexterity=1, constitution=3),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=10,
                 faction="undead"),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
    }

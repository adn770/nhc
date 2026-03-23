"""Llop d'Hivern (Winter Wolf) — frost breath on attacks. (BEB: Llop d'hivern)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    FrostBreath,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("winter_wolf")
def create_winter_wolf() -> dict:
    return {
        "Renderable": Renderable(glyph="W", color="bright_white", render_order=2),
        "Description": creature_desc("winter_wolf"),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=17, maximum=17),
        "Weapon": Weapon(damage="2d4"),
        "FrostBreath": FrostBreath(dice="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
    }

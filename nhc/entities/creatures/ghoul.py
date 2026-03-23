"""Gul (Ghoul) — undead creature that drains life. (BEB: Gul)"""

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


@EntityRegistry.register_creature("ghoul")
def create_ghoul() -> dict:
    return {
        "Renderable": Renderable(glyph="g", color="cyan", render_order=2),
        "Description": creature_desc("ghoul"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d4"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
        "Undead": Undead(),
        "DrainTouch": True,
    }

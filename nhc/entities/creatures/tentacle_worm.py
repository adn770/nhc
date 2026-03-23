"""Cuc de Tentacles (Tentacle Worm) — grasping cave predator. (BEB: Cuc de tentacles)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("tentacle_worm")
def create_tentacle_worm() -> dict:
    return {
        "Renderable": Renderable(glyph="w", color="purple", render_order=2),
        "Description": creature_desc("tentacle_worm"),
        "Stats": Stats(strength=2, dexterity=1),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

"""Stirge — blood-draining flying pest. (BEB: Estirge)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    BloodDrain,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("stirge")
def create_stirge() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="red", render_order=2),
        "Description": creature_desc("stirge"),
        "Stats": Stats(strength=1, dexterity=4),
        "Health": Health(current=4, maximum=4),
        "BloodDrain": BloodDrain(drain_per_hit=2),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
    }

"""Sangonera Gegant (Giant Leech) — blood-draining swamp horror. (BEB: Sangonera gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    BloodDrain,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_leech")
def create_giant_leech() -> dict:
    return {
        "Renderable": Renderable(glyph="l", color="dark_red", render_order=2),
        "Description": creature_desc("giant_leech"),
        "Stats": Stats(strength=1, dexterity=2),
        "Health": Health(current=9, maximum=9),
        "BloodDrain": BloodDrain(drain_per_hit=3),
        "AI": AI(behavior="aggressive_melee", morale=10),
        "BlocksMovement": BlocksMovement(),
    }

"""Mimic — disguises itself as a chest, ambushes the player. (BEB: Mímesi)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Disguise,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("mimic")
def create_mimic() -> dict:
    return {
        "Renderable": Renderable(glyph="$", color="yellow", render_order=2),
        "Description": creature_desc("mimic"),
        "Stats": Stats(strength=4, dexterity=2),
        "Health": Health(current=22, maximum=22),
        "Weapon": Weapon(damage="2d6"),
        "Disguise": Disguise(appears_as="chest", reveal_on="interact"),
        "AI": AI(behavior="guard", morale=12),
        "BlocksMovement": BlocksMovement(),
    }

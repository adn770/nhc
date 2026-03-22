"""Cocatriu (Cockatrice) — touch petrifies. (BEB: Cocatriu)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    PetrifyingTouch,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("cocatriu")
def create_cocatriu() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="yellow", render_order=2),
        "Description": creature_desc("cocatriu"),
        "Stats": Stats(strength=1, dexterity=3),
        "Health": Health(current=17, maximum=17),
        "Weapon": Weapon(damage="1d6"),
        "PetrifyingTouch": PetrifyingTouch(),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
    }

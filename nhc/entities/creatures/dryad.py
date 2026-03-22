"""Dryad — forest spirit that charms with a touch. (BEB: Dríade)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("dryad")
def create_dryad() -> dict:
    return {
        "Renderable": Renderable(glyph="d", color="green", render_order=2),
        "Description": creature_desc("dryad"),
        "Stats": Stats(strength=1, dexterity=4),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d4"),
        # Charm on touch: reuse DrainTouch logic shape but for charm
        # Handled via CharmTouch tag (same as VenomousStrike pattern)
        "CharmTouch": True,
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
    }

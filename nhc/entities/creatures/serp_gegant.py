"""Serp Gegant (Giant Snake) — constricting venomous serpent. (BEB: Serp gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("serp_gegant")
def create_serp_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="S", color="green", render_order=2),
        "Description": creature_desc("serp_gegant"),
        "Stats": Stats(strength=2, dexterity=2),
        "Health": Health(current=11, maximum=11),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=9),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

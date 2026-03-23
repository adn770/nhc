"""Escorpí Gegant (Giant Scorpion) — venomous arachnid. (BEB: Escorpí gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_scorpion")
def create_giant_scorpion() -> dict:
    return {
        "Renderable": Renderable(glyph="s", color="yellow", render_order=2),
        "Description": creature_desc("giant_scorpion"),
        "Stats": Stats(strength=3, dexterity=3),
        "Health": Health(current=14, maximum=14),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=11),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

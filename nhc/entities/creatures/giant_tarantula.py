"""Taràntula Gegant (Giant Tarantula) — venomous spider. (BEB: Taràntula gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
    Weapon,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_tarantula")
def create_giant_tarantula() -> dict:
    return {
        "Renderable": Renderable(glyph="S", color="brown", render_order=2),
        "Description": creature_desc("giant_tarantula"),
        "Stats": Stats(strength=1, dexterity=4),
        "Health": Health(current=9, maximum=9),
        "Weapon": Weapon(damage="1d6"),
        "AI": AI(behavior="aggressive_melee", morale=8),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

"""Centpeus Gegant (Giant Centipede) — weak venom. (BEB: Centpeus gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("centpeus_gegant")
def create_centpeus_gegant() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="dark_green", render_order=2),
        "Description": creature_desc("centpeus_gegant"),
        "Stats": Stats(strength=-1, dexterity=4),
        "Health": Health(current=2, maximum=2),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

"""Centpeus Gegant (Giant Centipede) — weak venom. (BEB: Centpeus gegant)"""

from nhc.entities.components import (
    AI,
    BlocksMovement,
    Health,
    Renderable,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("giant_centipede")
def create_giant_centipede() -> dict:
    return {
        "Renderable": Renderable(glyph="c", color="dark_green", render_order=2),
        "Description": creature_desc("giant_centipede"),
        "Stats": Stats(strength=-1, dexterity=4),
        "Health": Health(current=2, maximum=2),
        "AI": AI(behavior="aggressive_melee", morale=7),
        "BlocksMovement": BlocksMovement(),
        "VenomousStrike": True,
    }

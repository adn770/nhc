"""Farmer — rumour-dispensing NPC at inhabited sub-hex farms."""

from nhc.entities.components import (
    AI,
    Health,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("farmer")
def create_farmer() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_yellow", render_order=2,
        ),
        "Description": creature_desc("farmer"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=1, wisdom=2, charisma=1,
        ),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="idle", morale=5, faction="human"),
        "RumorVendor": RumorVendor(chatter_table="farmer.chatter"),
    }

"""Orchardist — rumour-dispensing NPC at sub-hex orchards."""

from nhc.entities.components import (
    AI,
    Health,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("orchardist")
def create_orchardist() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="green", render_order=2,
        ),
        "Description": creature_desc("orchardist"),
        "Stats": Stats(
            strength=1, dexterity=2, constitution=2,
            intelligence=1, wisdom=2, charisma=1,
        ),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="idle", morale=5, faction="human"),
        "RumorVendor": RumorVendor(chatter_table="orchardist.chatter"),
    }

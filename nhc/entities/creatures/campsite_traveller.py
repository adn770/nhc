"""Campsite traveller — wandering NPC who trades rumours at campfires."""

from nhc.entities.components import (
    AI,
    Health,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("campsite_traveller")
def create_campsite_traveller() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="brown", render_order=2,
        ),
        "Description": creature_desc("campsite_traveller"),
        "Stats": Stats(
            strength=1, dexterity=2, constitution=1,
            intelligence=2, wisdom=2, charisma=2,
        ),
        "Health": Health(current=7, maximum=7),
        "AI": AI(behavior="idle", morale=4, faction="human"),
        "RumorVendor": RumorVendor(),
    }

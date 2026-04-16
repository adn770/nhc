"""Innkeeper — non-combat NPC who dispenses overland rumors."""

from nhc.entities.components import (
    AI,
    Health,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("innkeeper")
def create_innkeeper() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="yellow", render_order=2,
        ),
        "Description": creature_desc("innkeeper"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=2, wisdom=2, charisma=3,
        ),
        "Health": Health(current=9, maximum=9),
        "AI": AI(behavior="idle", morale=4, faction="human"),
        "RumorVendor": RumorVendor(),
    }

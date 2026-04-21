"""Villager — town NPC wandering streets on errands."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("villager")
def create_villager() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="white", render_order=2,
        ),
        "Description": creature_desc("villager"),
        "Stats": Stats(
            strength=0, dexterity=1, constitution=1,
            intelligence=0, wisdom=1, charisma=1,
        ),
        "Health": Health(current=4, maximum=4),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Errand": Errand(),
    }

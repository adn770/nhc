"""Beggar — loiters the streets with an outstretched hand."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("beggar")
def create_beggar() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_black", render_order=2,
        ),
        "Description": creature_desc("beggar"),
        "Stats": Stats(
            strength=0, dexterity=1, constitution=0,
            intelligence=0, wisdom=1, charisma=0,
        ),
        "Health": Health(current=3, maximum=3),
        "AI": AI(behavior="errand", morale=2, faction="human"),
        "Errand": Errand(),
    }

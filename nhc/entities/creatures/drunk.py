"""Drunk — weaves between the tavern and the gutter."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("drunk")
def create_drunk() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="yellow", render_order=2,
        ),
        "Description": creature_desc("drunk"),
        "Stats": Stats(
            strength=1, dexterity=0, constitution=1,
            intelligence=0, wisdom=0, charisma=0,
        ),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Errand": Errand(),
    }

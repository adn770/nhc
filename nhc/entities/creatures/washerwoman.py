"""Washerwoman — launders linen by the well or river."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("washerwoman")
def create_washerwoman() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_magenta", render_order=2,
        ),
        "Description": creature_desc("washerwoman"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=0, wisdom=1, charisma=1,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Errand": Errand(),
    }

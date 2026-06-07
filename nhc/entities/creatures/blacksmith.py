"""Blacksmith — town smith working near the forge."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("blacksmith")
def create_blacksmith() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_red", render_order=2,
        ),
        "Description": creature_desc("blacksmith"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=1, wisdom=1, charisma=1,
        ),
        "Health": Health(current=10, maximum=10),
        "AI": AI(behavior="errand", morale=5, faction="human"),
        "Errand": Errand(),
    }

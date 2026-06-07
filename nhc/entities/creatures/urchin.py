"""Urchin — a street child darting through the crowd."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("urchin")
def create_urchin() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_green", render_order=2,
        ),
        "Description": creature_desc("urchin"),
        "Stats": Stats(
            strength=0, dexterity=2, constitution=0,
            intelligence=1, wisdom=0, charisma=1,
        ),
        "Health": Health(current=3, maximum=3),
        "AI": AI(behavior="errand", morale=2, faction="human"),
        "Errand": Errand(),
    }

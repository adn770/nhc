"""Pilgrim — devout traveller praying near a sacred site."""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("pilgrim")
def create_pilgrim() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="cyan", render_order=2,
        ),
        "Description": creature_desc("pilgrim"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=1, wisdom=3, charisma=1,
        ),
        "Health": Health(current=5, maximum=5),
        "AI": AI(behavior="idle", morale=3, faction="human"),
    }

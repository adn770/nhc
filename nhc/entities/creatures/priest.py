"""Priest — non-combat NPC offering temple services and holy goods."""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("priest")
def create_priest() -> dict:
    return {
        "Renderable": Renderable(glyph="@", color="bright_white",
                                 render_order=2),
        "Description": creature_desc("priest"),
        "Stats": Stats(strength=1, dexterity=1, constitution=2,
                       intelligence=2, wisdom=4, charisma=3),
        "Health": Health(current=12, maximum=12),
        "AI": AI(behavior="idle", morale=5, faction="human"),
    }

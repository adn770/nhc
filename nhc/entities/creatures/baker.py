"""Baker — town baker tending the oven."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("baker")
def create_baker() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="yellow", render_order=2,
        ),
        "Description": creature_desc("baker"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=1,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=4, faction="human"),
        "Errand": Errand(),
    }

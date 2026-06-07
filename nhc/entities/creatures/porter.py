"""Porter — hauls crates and barrels through the streets."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("porter")
def create_porter() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_white", render_order=2,
        ),
        "Description": creature_desc("porter"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=0, wisdom=0, charisma=0,
        ),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="errand", morale=4, faction="human"),
        "Errand": Errand(),
    }

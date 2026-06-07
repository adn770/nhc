"""Water carrier — hauls pails between the well and homes."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("water_carrier")
def create_water_carrier() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_cyan", render_order=2,
        ),
        "Description": creature_desc("water_carrier"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=2,
            intelligence=0, wisdom=1, charisma=0,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=3, faction="human"),
        "Errand": Errand(),
    }

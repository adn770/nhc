"""Hermit priest — reduced-service priest tending a mysterious temple.

Stationed in sandlands / icelands "mysterious" temples (design
§8). Structurally mirrors the regular priest but ships with a
reduced temple_services list via placement extra (just bless --
heal / remove_curse require a forest or mountain temple).
"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("hermit_priest")
def create_hermit_priest() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="white", render_order=2,
        ),
        "Description": creature_desc("hermit_priest"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=2,
            intelligence=2, wisdom=4, charisma=2,
        ),
        "Health": Health(current=10, maximum=10),
        "AI": AI(behavior="idle", morale=4, faction="human"),
    }

"""Town crier — walks a route calling out the hour."""

from nhc.entities.components import (
    AI, Crier, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("town_crier")
def create_town_crier() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="magenta", render_order=2,
        ),
        "Description": creature_desc("town_crier"),
        "Stats": Stats(
            strength=0, dexterity=1, constitution=1,
            intelligence=1, wisdom=1, charisma=2,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="patrol", morale=5, faction="human"),
        "Crier": Crier(),
    }

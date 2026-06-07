"""Town guard — patrols the streets, converges on incidents."""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("town_guard")
def create_town_guard() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_blue", render_order=2,
        ),
        "Description": creature_desc("town_guard"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=1, wisdom=1, charisma=1,
        ),
        "Health": Health(current=12, maximum=12),
        "AI": AI(behavior="patrol", morale=8, faction="human"),
    }

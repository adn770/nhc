"""Watch captain — leads the town watch on its rounds."""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("watch_captain")
def create_watch_captain() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="blue", render_order=2,
        ),
        "Description": creature_desc("watch_captain"),
        "Stats": Stats(
            strength=2, dexterity=2, constitution=2,
            intelligence=1, wisdom=2, charisma=2,
        ),
        "Health": Health(current=16, maximum=16),
        "AI": AI(behavior="patrol", morale=10, faction="human"),
    }

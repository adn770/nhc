"""Preacher — exhorts passers-by from a fixed spot."""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("preacher")
def create_preacher() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="white", render_order=2,
        ),
        "Description": creature_desc("preacher"),
        "Stats": Stats(
            strength=1, dexterity=0, constitution=1,
            intelligence=1, wisdom=2, charisma=2,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=4, faction="human"),
        "Errand": Errand(),
    }

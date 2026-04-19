"""Hermit — reclusive forest-dwelling NPC.

A friendly old recluse living in a forest cottage. Non-combat,
neutral faction. Rolling up dialogue / quests is deferred to the
narrative-systems milestone; v2 just gets the hermit placed
indoors so the door-crossing handler delivers the encounter on
entry.
"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("hermit")
def create_hermit() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="green", render_order=2,
        ),
        "Description": creature_desc("hermit"),
        "Stats": Stats(
            strength=0, dexterity=0, constitution=0,
            intelligence=2, wisdom=3, charisma=1,
        ),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="idle", morale=3, faction="neutral"),
    }

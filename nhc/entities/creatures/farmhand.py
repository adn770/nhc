"""Farmhand — silent farm-worker NPC on the surface fields.

The farmer (rumour vendor) lives inside the farmhouse; farmhands
work the surrounding fields. Idle behaviour, no rumours — they
are population dressing that makes a farm read as a working
place rather than an empty plot.
"""

from nhc.entities.components import (
    AI, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("farmhand")
def create_farmhand() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="yellow", render_order=2,
        ),
        "Description": creature_desc("farmhand"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=0, wisdom=1, charisma=0,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="idle", morale=4, faction="human"),
    }

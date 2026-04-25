"""Noble — landed gentry residing in a mansion or estate.

Wandering errand AI keeps them pacing the main hall rather
than rooted to a single tile; the populator stamps anchor_x /
anchor_y so they stay near where the spec dropped them.
"""

from nhc.entities.components import (
    AI, Errand, Health, Renderable, Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("noble")
def create_noble() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_magenta", render_order=2,
        ),
        "Description": creature_desc("noble"),
        "Stats": Stats(
            strength=1, dexterity=1, constitution=1,
            intelligence=2, wisdom=2, charisma=3,
        ),
        "Health": Health(current=6, maximum=6),
        "AI": AI(behavior="errand", morale=2, faction="human"),
        "Errand": Errand(anchor_weight=0.7),
    }

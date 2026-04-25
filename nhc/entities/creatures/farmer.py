"""Farmer — rumour-dispensing NPC at inhabited sub-hex farms."""

from nhc.entities.components import (
    AI,
    Errand,
    Health,
    Renderable,
    RumorVendor,
    Stats,
)
from nhc.entities.registry import EntityRegistry, creature_desc


@EntityRegistry.register_creature("farmer")
def create_farmer() -> dict:
    return {
        "Renderable": Renderable(
            glyph="@", color="bright_yellow", render_order=2,
        ),
        "Description": creature_desc("farmer"),
        "Stats": Stats(
            strength=2, dexterity=1, constitution=2,
            intelligence=1, wisdom=2, charisma=1,
        ),
        "Health": Health(current=8, maximum=8),
        "AI": AI(behavior="errand", morale=5, faction="human"),
        "RumorVendor": RumorVendor(chatter_table="farmer.chatter"),
        # Anchor weight 0.7 keeps the farmer pacing near the
        # interior tile they spawn on; populate_site_placements
        # stamps anchor_x / anchor_y to that tile at spawn time.
        "Errand": Errand(anchor_weight=0.7),
    }

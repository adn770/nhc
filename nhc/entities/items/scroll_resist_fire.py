"""Scroll of Resist Fire — halves fire damage. (BEB: Resistir foc)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_resist_fire")
def create_scroll_resist_fire() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_red", render_order=1),
        "Description": item_desc("scroll_resist_fire"),
        "Consumable": Consumable(effect="resist_fire", dice="12", slots=1),
    }

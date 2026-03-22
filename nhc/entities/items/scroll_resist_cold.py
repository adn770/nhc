"""Scroll of Resist Cold — halves cold damage. (BEB: Resistir fred)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_resist_cold")
def create_scroll_resist_cold() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_resist_cold"),
        "Consumable": Consumable(effect="resist_cold", dice="12", slots=1),
    }

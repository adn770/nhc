"""Scroll of Water Breathing — survive water tiles. (BEB: Respirar sota l'aigua)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_water_breathing")
def create_scroll_water_breathing() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="blue", render_order=1),
        "Description": item_desc("scroll_water_breathing"),
        "Consumable": Consumable(effect="water_breathing", dice="20", slots=1),
    }

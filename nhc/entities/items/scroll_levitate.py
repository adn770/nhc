"""Scroll of Levitate — float over traps and terrain. (BEB: Levitar)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_levitate")
def create_scroll_levitate() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="white", render_order=1),
        "Description": item_desc("scroll_levitate"),
        "Consumable": Consumable(effect="levitate", dice="12", slots=1),
    }

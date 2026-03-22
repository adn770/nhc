"""Scroll of Remove Fear — cures paralysis and fear effects. (BEB: Treure por)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_remove_fear")
def create_scroll_remove_fear() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="white", render_order=1),
        "Description": item_desc("scroll_remove_fear"),
        "Consumable": Consumable(effect="remove_fear", dice="0", slots=1),
    }

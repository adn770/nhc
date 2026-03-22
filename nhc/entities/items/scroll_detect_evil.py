"""Scroll of Detect Evil — reveals hostile creatures through walls. (BEB: Detectar el mal)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_evil")
def create_scroll_detect_evil() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": item_desc("scroll_detect_evil"),
        "Consumable": Consumable(effect="detect_evil", dice="0", slots=1),
    }

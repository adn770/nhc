"""Scroll of Detect Magic — reveals magic items on the level. (BEB: Detectar màgia)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_magic")
def create_scroll_detect_magic() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_detect_magic"),
        "Consumable": Consumable(effect="detect_magic", dice="0", slots=1),
    }

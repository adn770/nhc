"""Scroll of Detect Invisibility — reveals invisible creatures. (BEB: Detectar invisibilitat)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_invisibility")
def create_scroll_detect_invisibility() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_detect_invisibility"),
        "Consumable": Consumable(effect="detect_invisibility", dice="12", slots=1),
    }

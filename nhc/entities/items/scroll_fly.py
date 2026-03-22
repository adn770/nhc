"""Scroll of Fly — free movement for N turns. (BEB: Volar)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_fly")
def create_scroll_fly() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": item_desc("scroll_fly"),
        "Consumable": Consumable(effect="fly", dice="6", slots=1),
    }

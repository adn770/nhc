"""Scroll of Light — increases FOV radius temporarily. (BEB: Llum)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_light")
def create_scroll_light() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_yellow", render_order=1),
        "Description": item_desc("scroll_light"),
        "Consumable": Consumable(effect="light", dice="20", slots=1),
    }

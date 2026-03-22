"""Scroll of Haste — doubles attacks for 3 turns. (BEB: Apressar)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_haste")
def create_scroll_haste() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="yellow", render_order=1),
        "Description": item_desc("scroll_haste"),
        # dice = duration in turns
        "Consumable": Consumable(effect="haste", dice="3", slots=1),
    }

"""Scroll of Bless — grants +1 to attacks and damage. (BEB: Beneir)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_bless")
def create_scroll_bless() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": item_desc("scroll_bless"),
        # dice = duration in turns
        "Consumable": Consumable(effect="bless", dice="6", slots=1),
    }

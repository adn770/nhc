"""Scroll of Identify — reveals the true nature of one item."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_identify")
def create_scroll_identify() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": item_desc("scroll_identify"),
        "Consumable": Consumable(effect="identify", dice="0", slots=1),
    }

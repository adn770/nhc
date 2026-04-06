"""Scroll of Detect Food — reveals food on the level."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_food")
def create_scroll_detect_food() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_green", render_order=1),
        "Description": item_desc("scroll_detect_food"),
        "Consumable": Consumable(effect="detect_food", dice="0", slots=1),
    }

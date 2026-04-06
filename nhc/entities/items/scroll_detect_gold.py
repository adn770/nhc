"""Scroll of Detect Gold — reveals gold on the level."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_gold")
def create_scroll_detect_gold() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_yellow", render_order=1),
        "Description": item_desc("scroll_detect_gold"),
        "Consumable": Consumable(effect="detect_gold", dice="0", slots=1),
    }

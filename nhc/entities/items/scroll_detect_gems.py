"""Scroll of Detect Gems — reveals gems on the level."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_detect_gems")
def create_scroll_detect_gems() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_magenta", render_order=1),
        "Description": item_desc("scroll_detect_gems"),
        "Consumable": Consumable(effect="detect_gems", dice="0", slots=1),
    }

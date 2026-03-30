"""Scroll of Charging — restores charges to a wand."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_charging")
def create_scroll_charging() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_blue",
                                 render_order=1),
        "Description": item_desc("scroll_charging"),
        "Consumable": Consumable(effect="charging", dice="2d6",
                                 slots=1),
    }

"""Scroll of Reveal Map — memorizes the entire current level."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_reveal_map")
def create_scroll_reveal_map() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white", render_order=1),
        "Description": item_desc("scroll_reveal_map"),
        "Consumable": Consumable(effect="reveal_map", dice="0", slots=1),
    }

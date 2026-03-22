"""Scroll of Clairvoyance — reveals map in radius. (BEB: Clarividència)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_clairvoyance")
def create_scroll_clairvoyance() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_cyan", render_order=1),
        "Description": item_desc("scroll_clairvoyance"),
        "Consumable": Consumable(effect="clairvoyance", dice="0", slots=1),
    }

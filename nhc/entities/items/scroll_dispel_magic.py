"""Scroll of Dispel Magic — removes status effects in radius. (BEB: Dissipar màgia)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_dispel_magic")
def create_scroll_dispel_magic() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="white", render_order=1),
        "Description": item_desc("scroll_dispel_magic"),
        "Consumable": Consumable(effect="dispel_magic", dice="0", slots=1),
    }

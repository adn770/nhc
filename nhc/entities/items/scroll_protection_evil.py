"""Scroll of Protection from Evil — +1 saves, -1 enemy attacks. (BEB: Protecció del mal)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_protection_evil")
def create_scroll_protection_evil() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_blue", render_order=1),
        "Description": item_desc("scroll_protection_evil"),
        # dice = duration in turns
        "Consumable": Consumable(effect="protection_evil", dice="12", slots=1),
    }

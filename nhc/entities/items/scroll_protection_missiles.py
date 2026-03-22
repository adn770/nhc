"""Scroll of Protection from Missiles — immune to ranged attacks. (BEB: Protecció de projectils)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_protection_missiles")
def create_scroll_protection_missiles() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="blue", render_order=1),
        "Description": item_desc("scroll_protection_missiles"),
        "Consumable": Consumable(effect="protection_missiles", dice="12", slots=1),
    }

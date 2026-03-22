"""Scroll of Infravision — see in the dark, extended FOV. (BEB: Infravisió)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_infravision")
def create_scroll_infravision() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="red", render_order=1),
        "Description": item_desc("scroll_infravision"),
        "Consumable": Consumable(effect="infravision", dice="20", slots=1),
    }

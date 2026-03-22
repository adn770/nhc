"""Scroll of Find Traps — reveals hidden traps on the level. (BEB: Trobar trampes)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_find_traps")
def create_scroll_find_traps() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="yellow", render_order=1),
        "Description": item_desc("scroll_find_traps"),
        "Consumable": Consumable(effect="find_traps", dice="0", slots=1),
    }

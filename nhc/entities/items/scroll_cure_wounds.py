"""Scroll of Cure Wounds — heals 1d6+1 HP. (BEB: Curar ferides lleus)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_cure_wounds")
def create_scroll_cure_wounds() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="green", render_order=1),
        "Description": item_desc("scroll_cure_wounds"),
        "Consumable": Consumable(effect="heal", dice="1d6+1", slots=1),
    }

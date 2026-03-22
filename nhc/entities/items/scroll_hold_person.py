"""Scroll of Hold Person — paralyzes humanoids. (BEB: Retenir persona)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_hold_person")
def create_scroll_hold_person() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="yellow", render_order=1),
        "Description": item_desc("scroll_hold_person"),
        # dice = duration in turns; targets 1d4 visible humanoids
        "Consumable": Consumable(effect="hold_person", dice="9", slots=1),
    }

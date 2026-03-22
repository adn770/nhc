"""Scroll of Continual Light — permanent light source. (BEB: Llum contínua)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_continual_light")
def create_scroll_continual_light() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_yellow", render_order=1),
        "Description": item_desc("scroll_continual_light"),
        "Consumable": Consumable(effect="continual_light", dice="0", slots=1),
    }

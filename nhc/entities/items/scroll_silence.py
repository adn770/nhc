"""Scroll of Silence — prevents spellcasting in radius. (BEB: Silenci)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_silence")
def create_scroll_silence() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="grey", render_order=1),
        "Description": item_desc("scroll_silence"),
        "Consumable": Consumable(effect="silence", dice="12", slots=1),
    }

"""Scroll of Shield — temporary AC boost. (BEB: Escut màgic)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_shield")
def create_scroll_shield() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="cyan", render_order=1),
        "Description": item_desc("scroll_shield"),
        "Consumable": Consumable(effect="shield", dice="8", slots=1),
    }

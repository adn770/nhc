"""Scroll of Magic Missile — auto-hits target for 1d6+1. (BEB: Projectil màgic)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_magic_missile")
def create_scroll_magic_missile() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_white",
                                 render_order=1),
        "Description": item_desc("scroll_magic_missile"),
        # magic_missile never misses (no attack roll)
        "Consumable": Consumable(effect="magic_missile", dice="1d6+1",
                                 slots=1),
    }

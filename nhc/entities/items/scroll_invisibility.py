"""Scroll of Invisibility — caster becomes invisible. (BEB: Invisibilitat)"""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("scroll_invisibility")
def create_scroll_invisibility() -> dict:
    return {
        "Renderable": Renderable(glyph="?", color="bright_black", render_order=1),
        "Description": item_desc("scroll_invisibility"),
        # dice = duration in turns; breaks when player attacks
        "Consumable": Consumable(effect="invisibility", dice="6", slots=1),
    }

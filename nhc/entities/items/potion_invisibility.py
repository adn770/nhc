"""Potion of Invisibility — become unseen."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_invisibility")
def create_potion_invisibility() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_black", render_order=1),
        "Description": item_desc("potion_invisibility"),
        "Consumable": Consumable(effect="invisibility", dice="8", slots=1),
    }

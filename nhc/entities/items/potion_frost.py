"""Potion of Frost — freezes nearby creatures."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_frost")
def create_potion_frost() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_cyan", render_order=1),
        "Description": item_desc("potion_frost"),
        "Consumable": Consumable(effect="frost", dice="3", slots=1),
    }

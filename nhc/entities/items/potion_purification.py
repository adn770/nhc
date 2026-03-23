"""Potion of Purification — cures poison and status effects."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_purification")
def create_potion_purification() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_green", render_order=1),
        "Description": item_desc("potion_purification"),
        "Consumable": Consumable(effect="remove_fear", dice="0", slots=1),
    }

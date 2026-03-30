"""Potion of Strength — permanently increases STR by 1."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_strength")
def create_potion_strength() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_red", render_order=1),
        "Description": item_desc("potion_strength"),
        "Consumable": Consumable(effect="strength", dice="1", slots=1),
        "Throwable": Throwable(),
    }

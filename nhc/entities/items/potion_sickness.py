"""Potion of Sickness — damages and poisons the drinker or target."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_sickness")
def create_potion_sickness() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="green", render_order=1),
        "Description": item_desc("potion_sickness"),
        "Consumable": Consumable(effect="sickness", dice="2d4", slots=1),
        "Throwable": Throwable(),
    }

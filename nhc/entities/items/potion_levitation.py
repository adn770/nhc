"""Potion of Levitation — float over traps."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_levitation")
def create_potion_levitation() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="white", render_order=1),
        "Description": item_desc("potion_levitation"),
        "Consumable": Consumable(effect="levitate", dice="12", slots=1),
    }

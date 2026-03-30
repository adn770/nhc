"""Potion of Paralytic Gas — paralyzes nearby creatures."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_paralytic_gas")
def create_potion_paralytic_gas() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="yellow", render_order=1),
        "Description": item_desc("potion_paralytic_gas"),
        "Consumable": Consumable(effect="hold_person", dice="4", slots=1),
        "Throwable": Throwable(),
    }

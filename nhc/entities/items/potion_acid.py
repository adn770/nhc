"""Potion of Acid — deals acid damage, cures petrification."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_acid")
def create_potion_acid() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_white", render_order=1),
        "Description": item_desc("potion_acid"),
        "Consumable": Consumable(effect="acid", dice="1d4", slots=1),
        "Throwable": Throwable(),
    }

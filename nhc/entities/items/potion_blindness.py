"""Potion of Blindness — blinds drinker or thrown target."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_blindness")
def create_potion_blindness() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_black", render_order=1),
        "Description": item_desc("potion_blindness"),
        "Consumable": Consumable(effect="blindness", dice="8", slots=1),
        "Throwable": Throwable(),
    }

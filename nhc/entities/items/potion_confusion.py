"""Potion of Confusion — confuses drinker or thrown target."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_confusion")
def create_potion_confusion() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_magenta", render_order=1),
        "Description": item_desc("potion_confusion"),
        "Consumable": Consumable(effect="confusion", dice="6", slots=1),
        "Throwable": Throwable(),
    }

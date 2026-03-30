"""Potion of Speed — temporarily doubles movement speed."""

from nhc.entities.components import Throwable, Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("potion_speed")
def create_potion_speed() -> dict:
    return {
        "Renderable": Renderable(glyph="!", color="bright_green", render_order=1),
        "Description": item_desc("potion_speed"),
        "Consumable": Consumable(effect="speed", dice="8", slots=1),
        "Throwable": Throwable(),
    }

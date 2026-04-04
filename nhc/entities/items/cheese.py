"""Item — cheese."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("cheese")
def create_cheese() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow",
                                 render_order=1),
        "Description": item_desc("cheese"),
        "Consumable": Consumable(effect="satiate", dice="300"),
    }

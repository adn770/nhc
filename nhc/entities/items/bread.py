"""Item — bread."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("bread")
def create_bread() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow",
                                 render_order=1),
        "Description": item_desc("bread"),
        "Consumable": Consumable(effect="satiate", dice="300"),
    }

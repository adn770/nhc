"""Item — apple."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("apple")
def create_apple() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="green", render_order=1),
        "Description": item_desc("apple"),
        "Consumable": Consumable(effect="satiate", dice="200"),
    }

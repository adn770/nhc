"""Item — rations."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("rations")
def create_rations() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="yellow", render_order=1),
        "Description": item_desc("rations"),
        "Consumable": Consumable(effect="satiate", dice="400"),
    }

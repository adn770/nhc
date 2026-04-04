"""Item — dried meat."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("dried_meat")
def create_dried_meat() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="red", render_order=1),
        "Description": item_desc("dried_meat"),
        "Consumable": Consumable(effect="satiate", dice="350"),
    }

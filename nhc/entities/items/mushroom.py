"""Item — mushroom (random effect)."""

from nhc.entities.components import Consumable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("mushroom")
def create_mushroom() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="magenta",
                                 render_order=1),
        "Description": item_desc("mushroom"),
        "Consumable": Consumable(effect="mushroom", dice="250"),
    }

"""Item — sleeping bag."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("sleeping_bag")
def create_sleeping_bag() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="green", render_order=1),
        "Description": item_desc("sleeping_bag"),
    }

"""Item — tent."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("tent")
def create_tent() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="green", render_order=1),
        "Description": item_desc("tent"),
    }

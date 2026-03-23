"""Item — metal file."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("metal_file")
def create_metal_file() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="grey", render_order=1),
        "Description": item_desc("metal_file"),
    }

"""Item — waterskin."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("waterskin")
def create_waterskin() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="yellow", render_order=1),
        "Description": item_desc("waterskin"),
    }

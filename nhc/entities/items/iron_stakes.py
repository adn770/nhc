"""Item — iron stakes."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("iron_stakes")
def create_iron_stakes() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="cyan", render_order=1),
        "Description": item_desc("iron_stakes"),
    }

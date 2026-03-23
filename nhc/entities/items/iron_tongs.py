"""Item — iron tongs."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("iron_tongs")
def create_iron_tongs() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="cyan", render_order=1),
        "Description": item_desc("iron_tongs"),
    }

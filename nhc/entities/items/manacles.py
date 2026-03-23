"""Item — manacles."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("manacles")
def create_manacles() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="cyan", render_order=1),
        "Description": item_desc("manacles"),
    }

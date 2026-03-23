"""Item — perfume."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("perfume")
def create_perfume() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="magenta", render_order=1),
        "Description": item_desc("perfume"),
    }

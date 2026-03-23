"""Item — pick."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("pick")
def create_pick() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("pick"),
    }

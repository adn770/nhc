"""Item — hammer."""

from nhc.entities.components import Throwable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("hammer")
def create_hammer() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("hammer"),
        "Throwable": Throwable(),
    }

"""Item — instrument."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("instrument")
def create_instrument() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow", render_order=1),
        "Description": item_desc("instrument"),
    }

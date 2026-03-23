"""Item — tinderbox."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("tinderbox")
def create_tinderbox() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_red", render_order=1),
        "Description": item_desc("tinderbox"),
    }

"""Item — lens."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("lens")
def create_lens() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_white", render_order=1),
        "Description": item_desc("lens"),
    }

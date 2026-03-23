"""Item — rope ladder."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("rope_ladder")
def create_rope_ladder() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="yellow", render_order=1),
        "Description": item_desc("rope_ladder"),
    }

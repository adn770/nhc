"""Item — brigantine."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("brigantine")
def create_brigantine() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_yellow", render_order=1),
        "Description": item_desc("brigantine"),
        "Shield": True,
    }

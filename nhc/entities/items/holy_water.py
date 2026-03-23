"""Item — holy water."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("holy_water")
def create_holy_water() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_cyan", render_order=1),
        "Description": item_desc("holy_water"),
    }

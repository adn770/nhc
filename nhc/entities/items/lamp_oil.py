"""Item — lamp oil."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("lamp_oil")
def create_lamp_oil() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow", render_order=1),
        "Description": item_desc("lamp_oil"),
    }

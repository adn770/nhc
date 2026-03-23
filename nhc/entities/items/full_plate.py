"""Item — full plate."""

from nhc.entities.components import Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("full_plate")
def create_full_plate() -> dict:
    return {
        "Renderable": Renderable(glyph="[", color="bright_white", render_order=1),
        "Description": item_desc("full_plate"),
        "Shield": True,
    }

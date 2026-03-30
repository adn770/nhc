"""Item — vial."""

from nhc.entities.components import Throwable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("vial")
def create_vial() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("vial"),
        "Throwable": Throwable(),
    }

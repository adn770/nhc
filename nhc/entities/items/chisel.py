"""Item — chisel."""

from nhc.entities.components import Throwable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("chisel")
def create_chisel() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="white", render_order=1),
        "Description": item_desc("chisel"),
        "Throwable": Throwable(),
    }

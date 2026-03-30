"""Item — torch."""

from nhc.entities.components import Throwable, Renderable
from nhc.entities.registry import EntityRegistry, item_desc


@EntityRegistry.register_item("torch")
def create_torch() -> dict:
    return {
        "Renderable": Renderable(glyph="(", color="bright_yellow", render_order=1),
        "Description": item_desc("torch"),
        "Throwable": Throwable(),
    }
